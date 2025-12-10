from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.text import slugify


# ============================================================
# STORE CATEGORY
# ============================================================

class StoreCategory(models.Model):
    """
    Category for non-pool items:
    Examples:
      - Pump
      - Filter
      - Heater
      - Ionizer System
      - Accessories
      - Chemicals
    """
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)

    class Meta:
        verbose_name = "Store Category"
        verbose_name_plural = "Store Categories"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

# ============================================================
# ZIP LOCATION + SERVICE AREA
# ============================================================

class ServiceArea(models.Model):
    """
    High-level logical region you can toggle on/off.
    Example:
      - Florida Core
      - South Georgia
      - South Alabama
    Each service area carries its own permit base fees + labor hours.
    """
    name = models.CharField(max_length=100, unique=True)

    is_active = models.BooleanField(default=True)
    allow_pool_installs = models.BooleanField(default=True)
    allow_accessory_installs = models.BooleanField(default=True)

    # Base permit fees (what you pay the jurisdiction)
    permit_pool_fee_base = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Base government permit cost for pool installs in this area."
    )
    permit_accessory_fee_base = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Base government permit cost for accessory installs in this area."
    )

    # Labor hours required to handle permitting in this area
    permit_pool_labor_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Admin labor hours expected for pool permits in this area."
    )
    permit_accessory_labor_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Admin labor hours expected for accessory permits in this area."
    )

    notes = models.TextField(blank=True, help_text="Internal notes about this order.")

    install_disclaimer_accepted = models.BooleanField(
        default=False,
        help_text=(
            "True once the customer has explicitly accepted the install "
            "scheduling disclaimer at checkout."
        ),
    )

    class Meta:
        verbose_name = "County"
        verbose_name_plural = "Counties"
        ordering = ["name"]


    def __str__(self):
        return self.name

    # ---- Permit charge helpers (uses global hourly rate) ----

    def _get_hourly_rate(self) -> Decimal:
        from .models import GlobalSettings  # local import to avoid circular
        settings_obj = GlobalSettings.get_solo()
        return settings_obj.permit_labor_hourly_rate or Decimal("0.00")

    def get_pool_permit_charge(self) -> Decimal:
        """
        What the client sees as pool permit fee in this area:
          base permit fee + (labor hours * hourly rate)
        """
        rate = self._get_hourly_rate()
        return (self.permit_pool_fee_base or Decimal("0.00")) + (
            (self.permit_pool_labor_hours or Decimal("0.00")) * rate
        )

    def get_accessory_permit_charge(self) -> Decimal:
        """
        What the client sees as accessory permit fee in this area:
          base permit fee + (labor hours * hourly rate)
        """
        rate = self._get_hourly_rate()
        return (self.permit_accessory_fee_base or Decimal("0.00")) + (
            (self.permit_accessory_labor_hours or Decimal("0.00")) * rate
        )


class ZipLocation(models.Model):
    """
    Maps ZIP → city/county/state and a ServiceArea.
    Permit fees are defined at the ServiceArea level (county/group),
    not per ZIP.
    """
    zip_code = models.CharField(
        max_length=10,
        unique=True,
        help_text="5-digit ZIP (optionally ZIP+4)."
    )

    city = models.CharField(max_length=100, blank=True)
    county = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    service_area = models.ForeignKey(
        ServiceArea,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="zip_locations",
    )

    install_allowed = models.BooleanField(default=True)

    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "ZIP Location"
        verbose_name_plural = "ZIP Locations"
        ordering = ["state", "county", "zip_code"]

    def __str__(self):
        return f"{self.zip_code} – {self.city}, {self.state}"

    # Convenient passthroughs:

    def get_pool_permit_charge(self) -> Decimal:
        if self.service_area:
            return self.service_area.get_pool_permit_charge()
        return Decimal("0.00")

    def get_accessory_permit_charge(self) -> Decimal:
        if self.service_area:
            return self.service_area.get_accessory_permit_charge()
        return Decimal("0.00")

# ============================================================
# GLOBAL SETTINGS
# ============================================================

class GlobalSettings(models.Model):
    """
    Singleton-ish settings model.
    Use GlobalSettings.get_solo() to fetch the one row.
    """
    slug = models.CharField(
        max_length=50,
        unique=True,
        default="default",
        help_text="Do not change. Used to ensure a single settings row."
    )

    permit_labor_hourly_rate = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("50.00"),
        help_text="Hourly labor rate used to calculate permit labor charges."
    )
    base_zip_code = models.CharField(
        max_length=10,
        default="34491",
        help_text="Primary business ZIP for distance calculations."
    )

    class Meta:
        verbose_name = "Global Settings"
        verbose_name_plural = "Global Settings"

    def __str__(self):
        return "Global Settings"

    @classmethod
    def get_solo(cls) -> "GlobalSettings":
        obj, _ = cls.objects.get_or_create(slug="default")
        return obj


# ============================================================
# SHIPPING GROUP
# ============================================================

class ShippingGroup(models.Model):
    """
    Groups items/pools by shipping behavior.
    Examples:
      - Pool Freight
      - Accessory Parcel
      - LTL Equipment Pallet
    """
    code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Internal code, e.g. 'pool_freight', 'accessory_parcel'."
    )
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Human-readable name for this shipping group."
    )

    base_flat_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Base flat shipping rate (can be 0)."
    )

    per_mile_rate = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Optional per-mile shipping charge (0 = none)."
    )

    free_with_install = models.BooleanField(
        default=False,
        help_text="If true, shipping is free when installation is purchased."
    )

    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Shipping Group"
        verbose_name_plural = "Shipping Groups"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def estimate_cost(self, distance_miles: float, with_install: bool = False) -> Decimal:
        """
        Basic shipping cost estimate for this group.

        If free_with_install and with_install=True -> 0.
        Otherwise:
          cost = base_flat_rate + (distance_miles * per_mile_rate)
        """
        if self.free_with_install and with_install:
            return Decimal("0.00")

        cost = self.base_flat_rate or Decimal("0.00")
        if self.per_mile_rate and distance_miles is not None:
            cost += Decimal(str(distance_miles)) * (self.per_mile_rate or Decimal("0.00"))
        return cost


# ============================================================
# STORE ITEM (accessories, pumps, filters, heaters, etc.)
# ============================================================

class StoreItem(models.Model):
    category = models.ForeignKey(
        StoreCategory,
        on_delete=models.PROTECT,
        related_name="items",
        help_text="Category such as Pump, Filter, Heater, Accessory, Chemical, etc.",
    )

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)

    sku = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Internal SKU or manufacturer code."
    )

    description_short = models.CharField(
        max_length=255,
        blank=True,
        help_text="Short description for listings."
    )
    description_long = models.TextField(
        blank=True,
        help_text="Full description for product detail pages."
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Selling price for this item."
    )

    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)

    # Shipping group
    shipping_group = models.ForeignKey(
        ShippingGroup,
        on_delete=models.SET_NULL,
        related_name="store_items",
        null=True,
        blank=True,
        help_text="Defines how this item is shipped."
    )

    # Installation flags
    is_installable = models.BooleanField(default=False)
    install_base_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    install_included_miles = models.PositiveIntegerField(default=0)
    install_per_mile_rate = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    free_shipping_with_install = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["sku"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            new_slug = base_slug
            counter = 1
            while StoreItem.objects.filter(slug=new_slug).exclude(pk=self.pk).exists():
                counter += 1
                new_slug = f"{base_slug}-{counter}"
            self.slug = new_slug
        super().save(*args, **kwargs)

    def estimate_shipping_cost(self, distance_miles: float, with_install: bool = False) -> Decimal:
        """
        Convenience wrapper: shipping cost based on this item's shipping group.
        """
        if self.shipping_group:
            return self.shipping_group.estimate_cost(distance_miles, with_install=with_install)
        return Decimal("0.00")

    def estimate_install_cost(self, distance_miles: float) -> Decimal:
        """
        Install estimate for an accessory/equipment item.

        Formula:
          base = install_base_rate
          extra_miles = max(0, distance_miles - install_included_miles)
          mileage = extra_miles * install_per_mile_rate
        """
        if not self.is_installable:
            return Decimal("0.00")

        base = self.install_base_rate or Decimal("0.00")
        included = Decimal(str(self.install_included_miles or 0))
        distance = Decimal(str(distance_miles))

        extra_miles = distance - included
        if extra_miles < 0:
            extra_miles = Decimal("0.00")

        per_mile = self.install_per_mile_rate or Decimal("0.00")
        mileage_cost = extra_miles * per_mile

        return base + mileage_cost


# ============================================================
# POOL TYPE (Above-Ground, Semi-Inground, Inground, etc.)
# ============================================================

class PoolType(models.Model):
    """
    Represents a type of installation / configuration a pool family supports:
    - Above-Ground
    - Semi-Inground
    - Inground
    (You can add more later if needed.)
    """
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Pool Type"
        verbose_name_plural = "Pool Types"
        ordering = ["name"]

    def __str__(self):
        return self.name


# ============================================================
# POOL MODEL FAMILY (series-level info)
# ============================================================

class PoolModelFamily(models.Model):
    COMPAT_CHOICES = [
        ("recommended", "Recommended"),
        ("not_recommended", "Not Recommended"),
    ]

    name = models.CharField(max_length=200)
    brand = models.CharField(max_length=100, blank=True)

    # Multiple pool types (Above-Ground, Semi-Inground, Inground)
    pool_types = models.ManyToManyField(
        PoolType,
        related_name="pool_families",
        blank=True,
        help_text="Select all pool types this family can be installed as."
    )

    quality_label = models.CharField(max_length=100, blank=True)
    supports_custom_depth = models.BooleanField(default=False)

    salt_compatibility = models.CharField(
        max_length=20,
        choices=COMPAT_CHOICES,
        default="recommended",
        help_text="Saltwater system compatibility"
    )

    ionizer_compatibility = models.CharField(
        max_length=20,
        choices=COMPAT_CHOICES,
        default="recommended",
        help_text="Ionizer system compatibility"
    )

    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Pool Model Family"
        verbose_name_plural = "Pool Model Families"
        ordering = ["brand", "name"]

    def __str__(self):
        label = self.name
        if self.quality_label:
            label += f" – {self.quality_label}"
        return label

    def pool_types_list(self):
        return ", ".join(pt.name for pt in self.pool_types.all())
    pool_types_list.short_description = "Pool Types"


# ============================================================
# POOL VARIANT (shape + size + price + install)
# ============================================================

class PoolVariant(models.Model):
    SHAPE_CHOICES = [
        ("round", "Round"),
        ("oval", "Oval"),
        ("rectangle", "Rectangle"),
    ]

    family = models.ForeignKey(
        PoolModelFamily,
        on_delete=models.CASCADE,
        related_name="variants"
    )

    shape = models.CharField(
        max_length=20,
        choices=SHAPE_CHOICES,
        help_text="Geometric shape for this specific configuration."
    )

    # Shipping group for this pool variant
    shipping_group = models.ForeignKey(
        ShippingGroup,
        on_delete=models.SET_NULL,
        related_name="pool_variants",
        null=True,
        blank=True,
        help_text="Defines how this pool package is shipped when not installed."
    )

    # Dimensions
    diameter = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="For round/oval pools: diameter or long axis in feet."
    )
    length = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="For rectangle/oval: length in feet."
    )
    width = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="For rectangle/oval: width in feet."
    )

    wall_height_inches = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Standard wall height in inches (for above/semi)."
    )
    depth_label = models.CharField(
        max_length=100,
        blank=True,
        help_text='Human-friendly depth description (e.g. "52\" Wall", "3.5–5 ft").'
    )

    variant_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Base price for this specific size/depth package."
    )

    # Install pricing
    install_days = models.DecimalField(max_digits=4, decimal_places=1, default=1.0)
    install_daily_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    install_included_miles = models.PositiveIntegerField(default=0)
    install_per_mile_rate = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    is_active = models.BooleanField(default=True)
    sku = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        verbose_name = "Pool Variant"
        verbose_name_plural = "Pool Variants"
        ordering = ["family", "shape", "diameter", "length", "width"]

    def __str__(self):
        parts = [str(self.family)]
        size = self.size_label
        if size:
            parts.append(size)
        return " – ".join(parts)

    @property
    def size_label(self):
        """
        Human-readable size string for display.
        - For round pools: "<diameter>' Round"
        - For others (rectangle/oval): "<length>' x <width>'"
        """
        if self.shape == "round" and self.diameter:
            return f"{self.diameter}' Round"
        if self.length and self.width:
            return f"{self.length}' x {self.width}'"
        return "Custom Size"

    @property
    def total_base_price(self):
        return self.variant_price

    def estimate_shipping_cost(self, distance_miles: float, with_install: bool = False) -> Decimal:
        """
        Convenience wrapper: shipping cost based on this variant's shipping group.
        Note: your higher-level logic should pass with_install=True when
        the customer purchases installation, in which case shipping will often be 0.
        """
        if self.shipping_group:
            return self.shipping_group.estimate_cost(distance_miles, with_install=with_install)
        return Decimal("0.00")

    def estimate_install_cost(self, distance_miles: float) -> Decimal:
        """
        Basic install cost estimate for this pool variant.

        Formula:
          labor = install_days * install_daily_rate
          extra_miles = max(0, distance_miles - install_included_miles)
          mileage = extra_miles * install_per_mile_rate
        """
        labor_rate = self.install_daily_rate or Decimal("0.00")
        days = Decimal(str(self.install_days or 0))
        labor = labor_rate * days

        included = Decimal(str(self.install_included_miles or 0))
        distance = Decimal(str(distance_miles))

        extra_miles = distance - included
        if extra_miles < 0:
            extra_miles = Decimal("0.00")

        per_mile = self.install_per_mile_rate or Decimal("0.00")
        mileage_cost = extra_miles * per_mile

        return labor + mileage_cost


# ============================================================
# POOL PACKAGE COMPONENT (links variants to store items)
# ============================================================

class PoolPackageComponent(models.Model):
    COMPONENT_GROUP_CHOICES = [
        ("pump", "Pump"),
        ("filter", "Filter"),
        ("heater", "Heater"),
        ("ladder", "Ladder / Entry"),
        ("sanitizer", "Sanitizer"),
        ("plumbing", "Plumbing / Hoses"),
        ("accessory", "Accessory"),
        ("other", "Other"),
    ]

    pool_variant = models.ForeignKey(
        PoolVariant,
        on_delete=models.CASCADE,
        related_name="package_components"
    )

    item = models.ForeignKey(
        StoreItem,
        on_delete=models.PROTECT,
        related_name="pool_components"
    )

    component_group = models.CharField(max_length=30, choices=COMPONENT_GROUP_CHOICES)
    is_default = models.BooleanField(default=False)
    is_required = models.BooleanField(default=False)
    is_upgrade_only = models.BooleanField(default=False)

    option_group_code = models.CharField(
        max_length=50,
        blank=True,
        help_text="Items with the same code are mutually exclusive upgrade choices."
    )

    quantity = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Pool Package Component"
        verbose_name_plural = "Pool Package Components"
        ordering = ["pool_variant", "component_group", "item__name"]

    def __str__(self):
        return f"{self.pool_variant} – {self.item} ({self.component_group})"

# ============================================================
# ORDERS & ORDER ITEMS
# ============================================================


class Order(models.Model):
    STATUS_CHOICES = [
        ("cart", "In Cart"),
        ("pending", "Pending Payment"),
        ("paid", "Paid"),
        ("cancelled", "Cancelled"),
        ("refunded", "Refunded"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="orders",
        null=True,
        blank=True,
        help_text="Customer who placed the order."
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="cart",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Basic customer contact
    email = models.EmailField(blank=True)
    full_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=50, blank=True)

    # Location for install/permit
    zip_code = models.CharField(
        max_length=10,
        blank=True,
        help_text="Customer ZIP/postal code for this job."
    )
    zip_location = models.ForeignKey(
        "ZipLocation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        help_text="Linked ZIP record (county, state, etc.)."
    )

    install_disclaimer_accepted = models.BooleanField(
        default=False,
        help_text="Customer has accepted the installation disclaimer for this order."
    )

    # Install queue / scheduling
    install_service_area = models.ForeignKey(
        "ServiceArea",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders_for_install",
        help_text="Service area used for installation scheduling."
    )
    install_queue_position = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Position in the install queue within the service area."
    )

    # Totals
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    shipping_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    install_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    permit_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    notes = models.TextField(blank=True, help_text="Internal notes about this order.")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order #{self.id or 'NEW'} – {self.status}"

    def county_display(self) -> str:
        """
        For admin / UI display: service area name or county.
        """
        if self.zip_location and self.zip_location.service_area:
            return self.zip_location.service_area.name
        if self.zip_location:
            return self.zip_location.county or ""
        return ""

    def calculate_distance(self, zip_override: str | None = None):
        """
        Returns the distance in miles from the base ZIP to the customer's ZIP.

        If zip_override is provided, use that ZIP instead of the order's stored
        zip_code / zip_location. Requires both ZIP locations to have lat/lon.
        """
        from .utils import haversine_miles

        # GlobalSettings and ZipLocation are defined above in this file
        base_settings = GlobalSettings.get_solo()
        base_zip = base_settings.base_zip_code

        base_loc = ZipLocation.objects.filter(zip_code=base_zip).first()

        customer_loc = None

        # 1) If a zip_override is passed, use that
        if zip_override:
            customer_loc = ZipLocation.objects.filter(zip_code=zip_override).first()
        # 2) Else prefer explicit zip_location FK
        elif self.zip_location:
            customer_loc = self.zip_location
        # 3) Else fall back to stored zip_code
        elif self.zip_code:
            customer_loc = ZipLocation.objects.filter(zip_code=self.zip_code).first()

        if not (base_loc and customer_loc):
            return None

        if base_loc.latitude is None or customer_loc.latitude is None:
            return None

        return haversine_miles(
            base_loc.latitude,
            base_loc.longitude,
            customer_loc.latitude,
            customer_loc.longitude,
        )

    def recalc_totals(self):
        """
        Recalculate overall totals by summing child items.
        This DOES NOT recalculate per-line pricing; that is done in apply_pricing().
        """
        items = self.items.all()

        subtotal = Decimal("0.00")
        shipping_total = Decimal("0.00")
        install_total = Decimal("0.00")

        for item in items:
            subtotal += item.line_subtotal or Decimal("0.00")
            shipping_total += item.line_shipping_amount or Decimal("0.00")
            install_total += item.line_install_amount or Decimal("0.00")

        self.subtotal = subtotal
        self.shipping_total = shipping_total
        self.install_total = install_total

        # permit_total is set inside apply_pricing, not here
        self.tax_total = Decimal("0.00")  # placeholder for real tax logic later
        self.grand_total = (
            self.subtotal
            + self.shipping_total
            + self.install_total
            + self.permit_total
            + self.tax_total
        )

    def apply_pricing(self, distance_miles: float | None = None):
        """
        Central pricing engine for this order.

        If distance_miles is None, tries to calculate it from ZIP data.

        Steps:
          - sets unit_price on each line from the current product/variant price
          - recalculates line_subtotal
          - calculates line_install_amount using estimate_install_cost()
          - calculates line_shipping_amount using estimate_shipping_cost(), applying
            'free_with_install' rules at the shipping-group level.
          - calculates permit_total based on the order's county (ServiceArea)
        """
        # Auto-calc distance if not provided
        if distance_miles is None:
            distance_miles = self.calculate_distance()
            if distance_miles is None:
                distance_miles = 0  # fallback until you load lat/lon data

        # Preload related objects to avoid N+1 queries
        items = list(
            self.items.select_related(
                "pool_variant",
                "pool_variant__shipping_group",
                "store_item",
                "store_item__shipping_group",
            )
        )

        # Does this order contain ANY pool install?
        has_pool_install = any(
            (item.pool_variant is not None) and item.install_selected
            for item in items
        )

        # Does this order contain ANY accessory install (no pool variants)?
        has_accessory_install = any(
            (item.store_item is not None) and item.install_selected
            for item in items
        )

        # --------------------------
        # Resolve county (ServiceArea) from ZIP
        # --------------------------
        service_area = None

        if self.zip_location and self.zip_location.service_area:
            service_area = self.zip_location.service_area
        elif self.zip_code:
            z = ZipLocation.objects.filter(zip_code=self.zip_code).select_related("service_area").first()
            if z:
                self.zip_location = z
                if z.service_area:
                    service_area = z.service_area
                self.save(update_fields=["zip_location", "zip_code"])

        # --------------------------
        # Per-line pricing
        # --------------------------
        for item in items:
            # 1a) Base unit price
            base_price = Decimal("0.00")
            if item.pool_variant:
                base_price = item.pool_variant.variant_price or Decimal("0.00")
            elif item.store_item:
                base_price = item.store_item.price or Decimal("0.00")

            item.unit_price = base_price

            # Subtotal = unit_price * quantity
            item.recalc_line_totals()

            # 1b) Install cost
            install_amount = Decimal("0.00")
            if item.install_selected:
                if item.pool_variant:
                    per_item_install = item.pool_variant.estimate_install_cost(distance_miles)
                elif item.store_item:
                    per_item_install = item.store_item.estimate_install_cost(distance_miles)
                else:
                    per_item_install = Decimal("0.00")

                qty = Decimal(str(item.quantity or 0))
                install_amount = per_item_install * qty

            item.line_install_amount = install_amount

            # 1c) Shipping cost
            with_install_for_shipping = False

            if item.install_selected:
                with_install_for_shipping = True
            else:
                sg = None
                if item.pool_variant and item.pool_variant.shipping_group:
                    sg = item.pool_variant.shipping_group
                elif item.store_item and item.store_item.shipping_group:
                    sg = item.store_item.shipping_group

                if has_pool_install and sg and getattr(sg, "free_with_install", False):
                    with_install_for_shipping = True

            per_item_ship = Decimal("0.00")
            if item.pool_variant:
                per_item_ship = item.pool_variant.estimate_shipping_cost(
                    distance_miles,
                    with_install=with_install_for_shipping,
                )
            elif item.store_item:
                per_item_ship = item.store_item.estimate_shipping_cost(
                    distance_miles,
                    with_install=with_install_for_shipping,
                )

            qty = Decimal(str(item.quantity or 0))
            shipping_amount = per_item_ship * qty

            item.line_shipping_amount = shipping_amount

            # Save updated item fields
            item.save(
                update_fields=[
                    "unit_price",
                    "line_subtotal",
                    "line_install_amount",
                    "line_shipping_amount",
                ]
            )

        # --------------------------
        # Permit totals (county-based)
        # --------------------------
        permit_total = Decimal("0.00")
        if service_area:
            if has_pool_install:
                permit_total += service_area.get_pool_permit_charge()
            elif has_accessory_install:
                permit_total += service_area.get_accessory_permit_charge()

        self.permit_total = permit_total

        # --------------------------
        # Order-level totals
        # --------------------------
        self.recalc_totals()
        self.save(
            update_fields=[
                "subtotal",
                "shipping_total",
                "install_total",
                "permit_total",
                "tax_total",
                "grand_total",
            ]
        )

    def assign_install_queue_position(self) -> None:
        """
        Assign a simple install queue position within the service area.

        For now:
          - resolve install_service_area from zip_location.service_area
          - if no service_area, do nothing
          - if no queue position yet, set to (count of existing queued orders + 1)
        """
        # Determine service area
        service_area = None
        if self.zip_location and self.zip_location.service_area:
            service_area = self.zip_location.service_area

        if not service_area:
            return

        # Set install_service_area if different / missing
        if self.install_service_area_id != service_area.id:
            self.install_service_area = service_area
            self.save(update_fields=["install_service_area"])

        # If queue position already set, leave it
        if self.install_queue_position is not None:
            return

        # Naive queue: next integer in this service area
        next_pos = (
            Order.objects
            .filter(install_service_area=service_area)
            .exclude(install_queue_position__isnull=True)
            .count()
            + 1
        )
        self.install_queue_position = next_pos
        self.save(update_fields=["install_queue_position"])




class OrderItem(models.Model):
    """
    Single line item in an order.
    Can represent either:
      - a PoolVariant (pool package)
      - a StoreItem (accessory/equipment)
    Exactly ONE of pool_variant or store_item should be set.
    """
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )

    pool_variant = models.ForeignKey(
        PoolVariant,
        on_delete=models.PROTECT,
        related_name="order_items",
        null=True,
        blank=True,
    )

    store_item = models.ForeignKey(
        StoreItem,
        on_delete=models.PROTECT,
        related_name="order_items",
        null=True,
        blank=True,
    )

    quantity = models.PositiveIntegerField(default=1)

    # Snapshot of pricing at time of order
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    line_subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    # Shipping & install selections
    install_selected = models.BooleanField(default=False)
    line_install_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_shipping_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    # Future: store serialized choices (selected components/options, etc.)
    config_json = models.JSONField(
        blank=True,
        null=True,
        help_text="Serialized configuration (selected components/options)."
    )

    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Order Item"
        verbose_name_plural = "Order Items"

    def __str__(self):
        return f"{self.display_name} x {self.quantity}"

    @property
    def display_name(self) -> str:
        if self.pool_variant:
            return str(self.pool_variant)
        if self.store_item:
            return self.store_item.name
        return "Unknown Item"

    def recalc_line_totals(self):
        """
        Recalculate line_subtotal based on quantity and unit_price.
        Shipping/install amounts are expected to be set by higher-level
        business logic that calls PoolVariant/StoreItem estimate_* helpers.
        """
        q = Decimal(str(self.quantity or 0))
        self.line_subtotal = (self.unit_price or Decimal("0.00")) * q
