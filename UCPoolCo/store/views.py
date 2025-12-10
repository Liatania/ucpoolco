from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_GET
from django.shortcuts import render

import json
from decimal import Decimal

from .models import (
    ZipLocation,
    GlobalSettings,
    PoolType,
    PoolModelFamily,
    PoolVariant,
    StoreItem,
    Order,
    OrderItem,
    PoolPackageComponent,
)

from .utils import haversine_miles

def builder_page(request):
    """
    Customer-facing pool builder UI.

    This just renders the HTML/JS template; all business logic
    is handled by the existing JSON API endpoints.
    """
    return render(request, "store/builder.html")


def api_playground(request):
    """
    Minimal HTML page to exercise the API from a browser.
    Not for production, just a dev tool.
    """
    return render(request, "store/api_playground.html")

def home(request):
    """
    Simple test UI for the pool builder & cart API.
    """
    return render(request, "store/home.html")


@csrf_exempt  # you can later switch to proper CSRF handling for your frontend
@require_POST
def builder_zip_check(request):
    """
    API endpoint for the builder's first step:
      - validate ZIP
      - get county (ServiceArea)
      - compute distance from base ZIP
      - return install/permit info
    Expected JSON body: { "zip_code": "34491" }
    """
    import json

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "Invalid JSON body."},
            status=400,
        )

    zip_code = (data.get("zip_code") or "").strip()

    if not zip_code:
        return JsonResponse(
            {"ok": False, "error": "zip_code is required."},
            status=400,
        )

    # Look up customer ZIP
    zip_location = (
        ZipLocation.objects
        .select_related("service_area")
        .filter(zip_code=zip_code)
        .first()
    )

    if not zip_location:
        return JsonResponse(
            {"ok": False, "error": "ZIP code not found in service area database."},
            status=404,
        )

    service_area = zip_location.service_area

    # Base response skeleton
    resp = {
        "ok": True,
        "zip": {
            "zip_code": zip_location.zip_code,
            "city": zip_location.city,
            "county": zip_location.county,
            "state": zip_location.state,
        },
        "county": None,
        "distance_miles": None,
        "install": {
            "install_allowed_for_zip": bool(zip_location.install_allowed),
            "county_pool_installs_allowed": bool(service_area.allow_pool_installs) if service_area else False,
            "county_accessory_installs_allowed": bool(service_area.allow_accessory_installs) if service_area else False,
        },
        "permits": {
            "pool_permit_charge": None,
            "accessory_permit_charge": None,
        },
    }

    # If no county/service area attached, we stop here
    if not service_area:
        return JsonResponse(resp)

    # Fill in county info
    resp["county"] = {
        "name": service_area.name,
        "is_active": service_area.is_active,
    }

    # Permit charges (using your county + global hourly logic)
    pool_charge = service_area.get_pool_permit_charge()
    accessory_charge = service_area.get_accessory_permit_charge()

    resp["permits"]["pool_permit_charge"] = str(pool_charge)
    resp["permits"]["accessory_permit_charge"] = str(accessory_charge)

    # Distance calculation (base ZIP → customer ZIP)
    settings_obj = GlobalSettings.get_solo()
    base_zip = settings_obj.base_zip_code
    base_loc = (
        ZipLocation.objects
        .filter(zip_code=base_zip)
        .first()
    )

    if (
        base_loc
        and base_loc.latitude is not None and base_loc.longitude is not None
        and zip_location.latitude is not None and zip_location.longitude is not None
    ):
        distance = haversine_miles(
            base_loc.latitude,
            base_loc.longitude,
            zip_location.latitude,
            zip_location.longitude,
        )
        resp["distance_miles"] = round(distance, 2)

    return JsonResponse(resp)


def home(request):
    return render(request, "store/home.html")

@csrf_exempt
@require_POST
def builder_pool_options(request):
    """
    Builder Step 2:
    Given a ZIP, pool_type, and shape, return all matching pool families
    and their variants, with estimated install + shipping based on distance.
    Expected JSON body:
      {
        "zip_code": "34491",
        "pool_type": "above",      # PoolType.code
        "shape": "round"           # "round", "oval", "rectangle"
      }
    """
    import json

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "Invalid JSON body."},
            status=400,
        )

    zip_code = (data.get("zip_code") or "").strip()
    pool_type_code = (data.get("pool_type") or "").strip()
    shape = (data.get("shape") or "").strip()

    if not zip_code or not pool_type_code or not shape:
        return JsonResponse(
            {"ok": False, "error": "zip_code, pool_type, and shape are required."},
            status=400,
        )

    # --------------------------
    # Resolve ZIP & county
    # --------------------------
    zip_location = (
        ZipLocation.objects
        .select_related("service_area")
        .filter(zip_code=zip_code)
        .first()
    )

    if not zip_location:
        return JsonResponse(
            {"ok": False, "error": "ZIP code not found in service area database."},
            status=404,
        )

    service_area = zip_location.service_area

    # --------------------------
    # Compute distance (base ZIP -> customer ZIP)
    # --------------------------
    settings_obj = GlobalSettings.get_solo()
    base_zip = settings_obj.base_zip_code
    base_loc = ZipLocation.objects.filter(zip_code=base_zip).first()

    distance_miles = None
    if (
        base_loc
        and base_loc.latitude is not None and base_loc.longitude is not None
        and zip_location.latitude is not None and zip_location.longitude is not None
    ):
        distance_miles = haversine_miles(
            base_loc.latitude,
            base_loc.longitude,
            zip_location.latitude,
            zip_location.longitude,
        )
    else:
        distance_miles = 0.0  # fallback until you load lat/lon data

    # --------------------------
    # Resolve pool type
    # --------------------------
    pool_type = PoolType.objects.filter(code=pool_type_code).first()
    if not pool_type:
        return JsonResponse(
            {"ok": False, "error": f"Unknown pool_type code '{pool_type_code}'."},
            status=400,
        )

    # --------------------------
    # Find matching families + variants
    # --------------------------
    families = (
        PoolModelFamily.objects
        .filter(pool_types=pool_type)
        .distinct()
    )

    # Preload variants per family
    variants = (
        PoolVariant.objects
        .filter(family__in=families, shape=shape, is_active=True)
        .select_related("family", "shipping_group")
        .order_by("family__name", "diameter", "length", "width")

    )

    # Bucket variants by family
    family_map = {}
    for fam in families:
        family_map[fam.id] = {
            "family_id": fam.id,
            "family_name": fam.name,
            "brand": fam.brand,
            "quality_label": fam.quality_label,
            "supports_custom_depth": fam.supports_custom_depth,
            "salt_compatibility": fam.salt_compatibility,
            "ionizer_compatibility": fam.ionizer_compatibility,
            "notes": fam.notes,
            "variants": [],
        }

    # Attach variants
    for v in variants:
        # Estimated install & shipping at this distance (no install-selected yet)
        est_install = v.estimate_install_cost(distance_miles)
        est_shipping = v.estimate_shipping_cost(distance_miles, with_install=False)

        family_map[v.family_id]["variants"].append({
            "variant_id": v.id,
            "size_label": v.size_label,
            "shape": v.shape,
            "depth_label": v.depth_label,
            "base_price": str(v.variant_price or Decimal("0.00")),
            "estimated_install_cost": str(est_install),
            "estimated_shipping_cost": str(est_shipping),
        })

    # Filter out families with no variants for the given shape
    family_list = [f for f in family_map.values() if f["variants"]]

    return JsonResponse(
        {
            "ok": True,
            "zip": {
                "zip_code": zip_location.zip_code,
                "city": zip_location.city,
                "county": zip_location.county,
                "state": zip_location.state,
            },
            "county": {
                "name": service_area.name if service_area else None,
                "is_active": service_area.is_active if service_area else None,
                "install_allowed_for_zip": bool(zip_location.install_allowed),
                "county_pool_installs_allowed": bool(service_area.allow_pool_installs) if service_area else False,
            },
            "distance_miles": round(float(distance_miles), 2) if distance_miles is not None else None,
            "pool_type": {
                "code": pool_type.code,
                "name": pool_type.name,
            },
            "shape": shape,
            "families": family_list,
        }
    )
def _get_or_create_cart(request, zip_code=None):
    """
    Get the current 'cart' Order for this session, or create one.

    - Stores order_id in the session.
    - Optionally sets/updates zip_code on the order.
    """
    order_id = request.session.get("cart_order_id")
    order = None

    if order_id:
        try:
            order = Order.objects.get(id=order_id, status="cart")
        except Order.DoesNotExist:
            order = None

    if not order:
        # Create new cart order, with zip if provided
        order = Order.objects.create(
            status="cart",
            zip_code=zip_code or "",
        )
        request.session["cart_order_id"] = order.id
    else:
        # If we already have a cart and a new zip_code comes in, update it
        if zip_code and order.zip_code != zip_code:
            order.zip_code = zip_code
            order.save(update_fields=["zip_code"])

    return order

@csrf_exempt
@require_http_methods(["POST"])
def cart_configure_item(request, item_id: int):
    """
    Attach configuration (selected package components / upgrades)
    to a cart line item and re-price the cart.
    Expected JSON body:
    {
        "selected_components": [
            {"component_id": 5, "quantity": 1},
            {"component_id": 9, "quantity": 2}
        ]
    }
    """
    import json
    from decimal import Decimal
    from .models import PoolPackageComponent

    # Parse JSON body
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

    # Get cart
    order = _get_or_create_cart(request)
    if not order or order.status != "cart":
        return JsonResponse({"ok": False, "error": "Active cart not found."}, status=400)

    # Validate cart item exists in this cart
    try:
        item = order.items.select_related("pool_variant").get(id=item_id)
    except OrderItem.DoesNotExist:
        return JsonResponse({"ok": False, "error": f"Cart item id={item_id} not found."}, status=404)

    # Normalize incoming selected components
    raw_selected = data.get("selected_components", [])
    normalized = []
    comp_ids = []

    for entry in raw_selected:
        if not isinstance(entry, dict):
            continue

        cid = entry.get("component_id")
        if cid is None:
            continue

        try:
            cid_int = int(cid)
        except (TypeError, ValueError):
            continue

        qty = entry.get("quantity", 1)
        try:
            qty_int = int(qty)
        except (TypeError, ValueError):
            qty_int = 1

        if qty_int < 1:
            qty_int = 1

        comp_ids.append(cid_int)
        normalized.append({"component_id": cid_int, "quantity": qty_int})

    # Safety: ensure components belong to this pool variant
    if item.pool_variant and comp_ids:
        allowed_ids = set(
            PoolPackageComponent.objects
            .filter(pool_variant=item.pool_variant, id__in=comp_ids)
            .values_list("id", flat=True)
        )
        normalized = [c for c in normalized if c["component_id"] in allowed_ids]

    # Store config_json on the item
    item.config_json = {"selected_components": normalized}
    item.save(update_fields=["config_json"])

    # Recalculate pricing
    distance_miles = order.calculate_distance()
    order.apply_pricing(distance_miles=distance_miles)

    # Build response
    cart_items = []
    for li in order.items.select_related("pool_variant", "store_item"):
        cart_items.append(
            {
                "id": li.id,
                "display_name": li.display_name,
                "quantity": li.quantity,
                "unit_price": str(li.unit_price),
                "line_subtotal": str(li.line_subtotal),
                "line_install_amount": str(li.line_install_amount),
                "line_shipping_amount": str(li.line_shipping_amount),
                "config": li.config_json or {},
            }
        )

    return JsonResponse(
        {
            "ok": True,
            "order_id": order.id,
            "items": cart_items,
            "totals": {
                "subtotal": str(order.subtotal),
                "shipping_total": str(order.shipping_total),
                "install_total": str(order.install_total),
                "permit_total": str(order.permit_total),
                "tax_total": str(order.tax_total),
                "grand_total": str(order.grand_total),
            },
        }
    )


def _serialize_cart(order):
    """
    Returns a dict with cart items and totals for JSON responses.
    """
    items = []
    for li in order.items.select_related("pool_variant", "store_item"):
        if li.pool_variant:
            item_type = "pool"
            product_id = li.pool_variant.id
        elif li.store_item:
            item_type = "item"
            product_id = li.store_item.id
        else:
            item_type = "unknown"
            product_id = None

        items.append(
            {
                "id": li.id,
                "type": item_type,
                "product_id": product_id,
                "description": li.display_name,
                "quantity": li.quantity,
                "install_selected": li.install_selected,
                "unit_price": str(li.unit_price),
                "line_subtotal": str(li.line_subtotal),
                "line_install_amount": str(li.line_install_amount),
                "line_shipping_amount": str(li.line_shipping_amount),
            }
        )

    data = {
        "order_id": order.id,
        "status": order.status,
        "zip_code": order.zip_code,
        "totals": {
            "subtotal": str(order.subtotal),
            "shipping_total": str(order.shipping_total),
            "install_total": str(order.install_total),
            "permit_total": str(order.permit_total),
            "tax_total": str(order.tax_total),
            "grand_total": str(order.grand_total),
        },
        "items": items,
    }
    return data

@csrf_exempt
@require_http_methods(["POST"])
def cart_update_item(request, item_id):
    """
    Update a single line item in the cart.

    URL:  /api/cart/item/<item_id>/
    Body: { "quantity": 2, "install_selected": true }
    """
    from .models import Order, OrderItem

    # Parse JSON body
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

    quantity = data.get("quantity")
    install_selected = data.get("install_selected")

    # Get current cart
    order = _get_or_create_cart(request)

    # Get the item, ensure it belongs to this order
    try:
        line = OrderItem.objects.get(id=item_id, order=order)
    except OrderItem.DoesNotExist:
        return JsonResponse(
            {"ok": False, "error": f"Cart item id={item_id} not found."},
            status=404,
        )

    # Apply updates
    changed = False

    if quantity is not None:
        try:
            q = int(quantity)
            if q <= 0:
                # If quantity <= 0, treat as remove
                line.delete()
                # Reprice remaining items
                distance_miles = order.calculate_distance()
                order.apply_pricing(distance_miles)
                cart_data = _serialize_cart(order)
                return JsonResponse({"ok": True, "cart": cart_data})
            line.quantity = q
            changed = True
        except (TypeError, ValueError):
            return JsonResponse(
                {"ok": False, "error": "quantity must be a positive integer."},
                status=400,
            )

    if install_selected is not None:
        line.install_selected = bool(install_selected)
        changed = True

    if changed:
        line.save(update_fields=["quantity", "install_selected"])

    # Reprice after change
    distance_miles = order.calculate_distance()
    order.apply_pricing(distance_miles)

    cart_data = _serialize_cart(order)
    return JsonResponse({"ok": True, "cart": cart_data})

def _serialize_order(order):
    """
    Helper that turns an Order into a JSON-friendly dict.
    """
    items_data = []
    for li in order.items.select_related("pool_variant", "store_item"):
        items_data.append({
            "id": li.id,
            "display_name": li.display_name,
            "quantity": li.quantity,
            "install_selected": li.install_selected,
            "unit_price": str(li.unit_price),
            "line_subtotal": str(li.line_subtotal),
            "line_install_amount": str(li.line_install_amount),
            "line_shipping_amount": str(li.line_shipping_amount),
        })

    return {
        "order_id": order.id,
        "status": order.status,
        "zip_code": order.zip_code,
        "subtotal": str(order.subtotal),
        "shipping_total": str(order.shipping_total),
        "install_total": str(order.install_total),
        "permit_total": str(order.permit_total),
        "tax_total": str(order.tax_total),
        "grand_total": str(order.grand_total),
        "items": items_data,
    }


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def cart_item_update_delete(request, item_id):
    """
    POST:
      - {"quantity": N} to change quantity
      - {"install_selected": true/false} to toggle install
      - or both at once

    DELETE:
      - removes the item from the cart
    """
    try:
        line = (
            OrderItem.objects
            .select_related("order")
            .get(id=item_id, order__status="cart")
        )
    except OrderItem.DoesNotExist:
        return JsonResponse(
            {"ok": False, "error": f"Cart item id={item_id} not found."},
            status=404,
        )

    order = line.order

    if request.method == "DELETE":
        line.delete()
        # Recalculate using central pricing engine
        order.apply_pricing()
        return JsonResponse({"ok": True, "cart": _serialize_order(order)})

    # POST: update quantity and/or install_selected
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"ok": False, "error": "Invalid JSON body."},
            status=400,
        )

    quantity = data.get("quantity", None)
    install_selected = data.get("install_selected", None)

    # Handle quantity
    if quantity is not None:
        try:
            q = int(quantity)
        except (TypeError, ValueError):
            return JsonResponse(
                {"ok": False, "error": "Quantity must be an integer."},
                status=400,
            )

        if q <= 0:
            # Delete line if quantity <= 0
            line.delete()
            order.apply_pricing()
            return JsonResponse({"ok": True, "cart": _serialize_order(order)})

        line.quantity = q

    # Handle install flag
    if install_selected is not None:
        if isinstance(install_selected, str):
            install_flag = install_selected.lower() in ("1", "true", "yes", "on")
        else:
            install_flag = bool(install_selected)
        line.install_selected = install_flag

    line.save(update_fields=["quantity", "install_selected"])

    # Recalculate totals
    order.apply_pricing()

    return JsonResponse({"ok": True, "cart": _serialize_order(order)})


@csrf_exempt
@require_http_methods(["POST"])
def cart_remove_item(request, item_id):
    """
    Remove a single line item from the cart.

    URL:  /api/cart/item/<item_id>/remove/
    Body: (optional) {}
    """
    from .models import Order, OrderItem

    order = _get_or_create_cart(request)

    try:
        line = OrderItem.objects.get(id=item_id, order=order)
    except OrderItem.DoesNotExist:
        return JsonResponse(
            {"ok": False, "error": f"Cart item id={item_id} not found."},
            status=404,
        )

    line.delete()

    # Reprice remaining items
    distance_miles = order.calculate_distance()
    order.apply_pricing(distance_miles)

    cart_data = _serialize_cart(order)
    return JsonResponse({"ok": True, "cart": cart_data})

@csrf_exempt
@require_http_methods(["POST"])
def cart_add_item(request):
    """
    Add an item (pool or accessory) to the current cart.

    Expected JSON body:
    {
      "zip_code": "34491",
      "pool_variant_id": 1,     # optional, one of these two
      "store_item_id": 5,       # optional, one of these two
      "quantity": 1,
      "install_selected": true
    }
    """
    import json
    from .models import Order, OrderItem, PoolVariant, StoreItem, ZipLocation

    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse(
            {"ok": False, "error": "Invalid JSON."},
            status=400,
        )

    zip_code = data.get("zip_code", "")
    pool_variant_id = data.get("pool_variant_id")
    store_item_id = data.get("store_item_id")
    quantity = int(data.get("quantity", 1))
    install_selected = bool(data.get("install_selected", False))

    if not zip_code:
        return JsonResponse(
            {"ok": False, "error": "zip_code is required."},
            status=400,
        )

    # Verify ZIP is known and allowed
    zip_location = (
        ZipLocation.objects
        .select_related("service_area")
        .filter(zip_code=zip_code)
        .first()
    )
    if not zip_location:
        return JsonResponse(
            {
                "ok": False,
                "error": f"We do not currently service ZIP {zip_code}.",
            },
            status=400,
        )

    service_area = zip_location.service_area
    if not service_area or not service_area.is_active:
        return JsonResponse(
            {
                "ok": False,
                "error": f"We do not currently service ZIP {zip_code}.",
            },
            status=400,
        )

    # Get or create current cart order for this session
    order = _get_or_create_cart(request)
    # Ensure order knows the zip
    order.zip_code = zip_code
    order.zip_location = zip_location
    order.save(update_fields=["zip_code", "zip_location"])

    # Determine what we're adding
    pool_variant = None
    store_item = None

    if pool_variant_id:
        pool_variant = (
            PoolVariant.objects.filter(id=pool_variant_id, is_active=True).first()
        )
        if not pool_variant:
            return JsonResponse(
                {"ok": False, "error": f"PoolVariant id={pool_variant_id} not found or inactive."},
                status=400,
            )

    if store_item_id:
        store_item = (
            StoreItem.objects.filter(id=store_item_id, is_active=True).first()
        )
        if not store_item:
            return JsonResponse(
                {"ok": False, "error": f"StoreItem id={store_item_id} not found or inactive."},
                status=400,
            )

    if not pool_variant and not store_item:
        return JsonResponse(
            {"ok": False, "error": "Either pool_variant_id or store_item_id is required."},
            status=400,
        )

    # Create the line item
    line = OrderItem.objects.create(
        order=order,
        pool_variant=pool_variant,
        store_item=store_item,
        quantity=quantity,
        install_selected=install_selected,
    )

    # Recalculate pricing using our distance + pricing logic
    distance_miles = order.calculate_distance(zip_override=zip_code)
    order.apply_pricing(distance_miles)

    # Build response (full cart)
    cart_data = _serialize_cart(order)
    return JsonResponse({"ok": True, "cart": cart_data})

@csrf_exempt
@require_http_methods(["GET"])
def cart_summary(request):
    """
    Return the current cart (order in 'cart' status for this session).
    """
    from .models import Order

    order = _get_or_create_cart(request)
    # Optional: keep totals fresh
    distance_miles = order.calculate_distance()
    order.apply_pricing(distance_miles)

    cart_data = _serialize_cart(order)
    return JsonResponse({"ok": True, "cart": cart_data})


def cart_detail(request):
    """
    Return the current cart for this session.
    If there's no cart yet, return an empty cart with zero totals.
    """
    order_id = request.session.get("cart_order_id")
    order = None

    if order_id:
        try:
            order = Order.objects.get(id=order_id, status="cart")
        except Order.DoesNotExist:
            order = None

    if not order:
        # Empty cart response
        return JsonResponse(
            {
                "ok": True,
                "order_id": None,
                "status": "empty",
                "zip_code": None,
                "items": [],
                "totals": {
                    "subtotal": "0.00",
                    "install_total": "0.00",
                    "shipping_total": "0.00",
                    "permit_total": "0.00",
                    "tax_total": "0.00",
                    "grand_total": "0.00",
                },
            }
        )

    # Build item list
    cart_items = []
    for line in order.items.select_related("pool_variant", "store_item"):
        cart_items.append(
            {
                "id": line.id,
                "display_name": line.display_name,
                "quantity": line.quantity,
                "install_selected": line.install_selected,
                "unit_price": str(line.unit_price),
                "line_subtotal": str(line.line_subtotal),
                "line_install_amount": str(line.line_install_amount),
                "line_shipping_amount": str(line.line_shipping_amount),
            }
        )

    resp = {
        "ok": True,
        "order_id": order.id,
        "status": order.status,
        "zip_code": order.zip_code,
        "items": cart_items,
        "totals": {
            "subtotal": str(order.subtotal),
            "install_total": str(order.install_total),
            "shipping_total": str(order.shipping_total),
            "permit_total": str(order.permit_total),
            "tax_total": str(order.tax_total),
            "grand_total": str(order.grand_total),
        },
    }
    return JsonResponse(resp)

@csrf_exempt
@require_http_methods(["POST"])
def cart_update_zip(request):
    """
    Update the cart's ZIP code (and linked ZipLocation/ServiceArea), then re-price.
    Body:
      {
        "zip_code": "34491"
      }
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"ok": False, "error": "Invalid JSON body."},
            status=400,
        )

    zip_code = (data.get("zip_code") or "").strip()
    if not zip_code:
        return JsonResponse(
            {"ok": False, "error": "zip_code is required."},
            status=400,
        )

    zip_location = (
        ZipLocation.objects
        .select_related("service_area")
        .filter(zip_code=zip_code, install_allowed=True)
        .first()
    )
    if not zip_location or not zip_location.service_area or not zip_location.service_area.is_active:
        return JsonResponse(
            {"ok": False, "error": f"We do not currently service ZIP {zip_code}."},
            status=400,
        )

    # Get/create cart WITHOUT passing zip_code (your helper now supports both)
    order = _get_or_create_cart(request)

    # Update order's location fields
    order.zip_code = zip_code
    order.zip_location = zip_location
    order.save(update_fields=["zip_code", "zip_location"])

    # Recalculate pricing based on the new ZIP
    order.apply_pricing()

    return JsonResponse({"ok": True, "cart": _serialize_order(order)})


@csrf_exempt
@require_http_methods(["POST"])
def cart_checkout(request):
    import json

    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse(
            {"ok": False, "error": "Invalid JSON body."},
            status=400,
        )

    full_name = (data.get("full_name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    zip_code = (data.get("zip_code") or "").strip()
    install_disclaimer_accepted = bool(data.get("install_disclaimer_accepted", False))

    if not zip_code:
        return JsonResponse(
            {"ok": False, "error": "ZIP code is required."},
            status=400,
        )

    # Get current cart
    order = _get_or_create_cart(request)

    if not order.items.exists():
        return JsonResponse(
            {"ok": False, "error": "Cart is empty."},
            status=400,
        )

    # Attach contact info
    order.full_name = full_name
    order.email = email
    order.phone = phone
    order.zip_code = zip_code
    order.save(update_fields=["full_name", "email", "phone", "zip_code"])

    # Do we have any install-selected items?
    items = list(order.items.all())
    has_any_install = any(li.install_selected for li in items)

    # Enforce disclaimer if there is an install
    if has_any_install and not install_disclaimer_accepted:
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    "Install selected. You must acknowledge that install dates "
                    "are not guaranteed and may be affected by manufacturer delivery, "
                    "weather, vehicle issues, and other factors."
                ),
                "code": "install_disclaimer_required",
            },
            status=400,
        )

    # Apply pricing using stored ZIP / county
    order.apply_pricing()  # will auto-calc distance, permit, shipping, etc.

    # Mark disclaimer flag if relevant
    if has_any_install:
        order.install_disclaimer_accepted = True
        order.save(update_fields=["install_disclaimer_accepted"])

    # Set status to pending (you can change to 'paid' when payment provider confirms)
    order.status = "pending"
    order.save(update_fields=["status"])

    # Assign queue position if needed
    order.assign_install_queue_position()

    # Rebuild fresh items for response
    items = list(
        order.items.select_related("pool_variant", "store_item")
    )

    resp_items = []
    for li in items:
        resp_items.append(
            {
                "id": li.id,
                "display_name": li.display_name,
                "quantity": li.quantity,
                "unit_price": str(li.unit_price),
                "line_subtotal": str(li.line_subtotal),
                "line_install_amount": str(li.line_install_amount),
                "line_shipping_amount": str(li.line_shipping_amount),
                "install_selected": li.install_selected,
                "config": li.config_json or {},
            }
        )

    return JsonResponse(
        {
            "ok": True,
            "order_id": order.id,
            "status": order.status,
            "install_queue_position": order.install_queue_position,
            "install_service_area": (
                order.install_service_area.name if order.install_service_area else None
            ),
            "install_disclaimer_accepted": order.install_disclaimer_accepted,
            "items": resp_items,
            "totals": {
                "subtotal": str(order.subtotal),
                "shipping_total": str(order.shipping_total),
                "install_total": str(order.install_total),
                "permit_total": str(order.permit_total),
                "tax_total": str(order.tax_total),
                "grand_total": str(order.grand_total),
            },
        }
    )

@csrf_exempt
@require_GET
def cart_summary(request):
    """
    Return the current cart (status='cart') for this session,
    including items and totals.
    """
    order = _get_or_create_cart(request)

    items = []
    for li in order.items.select_related("pool_variant", "store_item"):
        items.append({
            "id": li.id,
            "display_name": li.display_name,
            "quantity": li.quantity,
            "unit_price": str(li.unit_price),
            "line_subtotal": str(li.line_subtotal),
            "install_selected": li.install_selected,
            "line_install_amount": str(li.line_install_amount),
            "line_shipping_amount": str(li.line_shipping_amount),
        })

    data = {
        "ok": True,
        "order_id": order.id,
        "status": order.status,
        "zip_code": order.zip_code,
        "totals": {
            "subtotal": str(order.subtotal),
            "shipping_total": str(order.shipping_total),
            "install_total": str(order.install_total),
            "permit_total": str(order.permit_total),
            "tax_total": str(order.tax_total),
            "grand_total": str(order.grand_total),
        },
        "items": items,
    }
    return JsonResponse(data)


@csrf_exempt
@require_GET
def order_summary(request, order_id: int):
    """
    Return a summary of a specific order (for confirmation page or
    a simple 'check my status' screen).
    """
    from .models import Order  # safe local import

    try:
        order = Order.objects.select_related("zip_location", "zip_location__service_area").get(pk=order_id)
    except Order.DoesNotExist:
        return JsonResponse(
            {"ok": False, "error": f"Order id={order_id} not found."},
            status=404,
        )

    items = []
    for li in order.items.select_related("pool_variant", "store_item"):
        items.append({
            "id": li.id,
            "display_name": li.display_name,
            "quantity": li.quantity,
            "unit_price": str(li.unit_price),
            "line_subtotal": str(li.line_subtotal),
            "install_selected": li.install_selected,
            "line_install_amount": str(li.line_install_amount),
            "line_shipping_amount": str(li.line_shipping_amount),
        })

    # Install queue info (we added these fields earlier)
    install_position = getattr(order, "install_queue_position", None)
    install_area = getattr(order, "install_queue_service_area", None)

    data = {
        "ok": True,
        "order_id": order.id,
        "status": order.status,
        "full_name": order.full_name,
        "email": order.email,
        "phone": order.phone,
        "zip_code": order.zip_code,
        "zip_location": {
            "zip_code": order.zip_location.zip_code if order.zip_location else None,
            "city": order.zip_location.city if order.zip_location else None,
            "county": order.zip_location.county if order.zip_location else None,
            "state": order.zip_location.state if order.zip_location else None,
            "service_area": order.zip_location.service_area.name
                if (order.zip_location and order.zip_location.service_area)
                else None,
        } if order.zip_location else None,
        "install_queue": {
            "position": install_position,
            "service_area": install_area,
        },
        "totals": {
            "subtotal": str(order.subtotal),
            "shipping_total": str(order.shipping_total),
            "install_total": str(order.install_total),
            "permit_total": str(order.permit_total),
            "tax_total": str(order.tax_total),
            "grand_total": str(order.grand_total),
        },
        "items": items,
    }
    return JsonResponse(data)


@csrf_exempt  # not strictly needed for GET, but safe
def builder_pool_components(request, variant_id):
    """
    Return default components + upgrade options for a given PoolVariant.

    URL: /api/builder/pool/<variant_id>/components/

    Response shape:

    {
      "ok": true,
      "variant": {
        "id": 1,
        "name": "Aurora – 26' Round",
        "size_label": "26' Round",
        "shape": "round",
        "depth_label": "52\" Wall",
        "family": {
          "id": 1,
          "name": "Aurora Series",
          "quality_tier": "Premium Steel",
          "salt_compatibility": "recommended",
          "ionizer_compatibility": "not_recommended",
          "pool_types": ["above", "semi"]
        }
      },
      "component_groups": [
        {
          "group": "pump",
          "label": "Pump",
          "required": true,
          "options": [
            {
              "item_id": 10,
              "name": "1.5 HP 2-Speed Pump",
              "sku": "PUMP-150-2SP",
              "is_default": true,
              "is_required": true,
              "price": "699.00",
              "is_installable": true,
              "install_base_rate": "150.00",
              "install_included_miles": 50,
              "install_per_mile_rate": "1.50",
            },
            ...
          ]
        },
        ...
      ]
    }
    """
    # Only allow GET for now
    if request.method != "GET":
        return JsonResponse(
            {"ok": False, "error": "Only GET is allowed for this endpoint."},
            status=405,
        )

    # Get the variant or return 404
    variant = (
        PoolVariant.objects
        .select_related("family")
        .filter(id=variant_id, is_active=True)
        .first()
    )
    if not variant:
        return JsonResponse(
            {"ok": False, "error": f"PoolVariant id={variant_id} not found or inactive."},
            status=404,
        )

    family = variant.family

    # Fetch all package components for this variant
    components = (
        PoolPackageComponent.objects
        .filter(pool_variant=variant)
        .select_related("item")
        .order_by("component_group", "id")
    )

    # Group them by component_group
    group_map = {}
    for comp in components:
        grp = comp.component_group
        if grp not in group_map:
            group_map[grp] = {
                "group": grp,
                "label": grp.replace("_", " ").title(),  # simple human label
                "required": False,
                "options": [],
            }

        group_entry = group_map[grp]

        # Mark group as required if ANY component in it is required
        if comp.is_required:
            group_entry["required"] = True

        item = comp.item

        group_entry["options"].append({
            "item_id": item.id,
            "name": item.name,
            "sku": item.sku,
            "is_default": comp.is_default,
            "is_required": comp.is_required,
            "price": str(item.price),
            "is_installable": item.is_installable,
            "install_base_rate": str(item.install_base_rate),
            "install_included_miles": item.install_included_miles,
            "install_per_mile_rate": str(item.install_per_mile_rate),
            "free_shipping_with_install": item.free_shipping_with_install,
        })

    # Build variant block
    # We assume these fields exist on PoolModelFamily:
    # - quality_tier
    # - salt_compatibility
    # - ionizer_compatibility
    # - pool_types (ManyToMany of PoolType with .code)
    pool_types = []
    if hasattr(family, "pool_types"):
        pool_types = list(family.pool_types.values_list("code", flat=True))

    variant_payload = {
        "id": variant.id,
        "name": str(variant),  # __str__ of PoolVariant
        "size_label": getattr(variant, "size_label", None),
        "shape": variant.shape,
        "depth_label": variant.depth_label,
        "family": {
            "id": family.id,
            "name": family.name,
            "quality_tier": getattr(family, "quality_tier", None),
            "salt_compatibility": getattr(family, "salt_compatibility", None),
            "ionizer_compatibility": getattr(family, "ionizer_compatibility", None),
            "pool_types": pool_types,
        },
    }

    resp = {
        "ok": True,
        "variant": variant_payload,
        "component_groups": list(group_map.values()),
    }
    return JsonResponse(resp)
