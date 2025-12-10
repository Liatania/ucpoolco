from django import forms
from django.contrib import admin

from .models import (
    StoreCategory,
    StoreItem,
    ShippingGroup,
    PoolType,
    PoolModelFamily,
    PoolVariant,
    PoolPackageComponent,
    ServiceArea,
    ZipLocation,
    GlobalSettings,
    Order,
    OrderItem,
)


# =======================
# STORE CATEGORY & ITEM
# =======================

@admin.register(StoreCategory)
class StoreCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(StoreItem)
class StoreItemAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "price",
        "shipping_group",
        "is_active",
        "is_installable",
        "install_base_rate",
    )
    list_filter = (
        "category",
        "shipping_group",
        "is_active",
        "is_featured",
        "is_installable",
    )
    search_fields = ("name", "sku", "description_short")
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("name",)}


# =======================
# SHIPPING GROUP
# =======================

@admin.register(ShippingGroup)
class ShippingGroupAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "base_flat_rate",
        "per_mile_rate",
        "free_with_install",
    )
    list_filter = ("free_with_install",)
    search_fields = ("name", "code")


# =======================
# COUNTIES (ServiceArea) & ZIP LOCATIONS
# =======================

class ServiceAreaForm(forms.ModelForm):
    """
    Custom form so that when you edit a County (ServiceArea),
    you can select multiple ZIP codes that belong to it.
    """
    zip_codes = forms.ModelMultipleChoiceField(
        queryset=ZipLocation.objects.all().order_by("zip_code"),
        required=False,
        widget=admin.widgets.FilteredSelectMultiple("ZIP codes", is_stacked=False),
        help_text="Select all ZIP codes that belong to this county.",
    )

    class Meta:
        model = ServiceArea
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # Pre-select all ZIPs currently assigned to this county
            self.fields["zip_codes"].initial = ZipLocation.objects.filter(
                service_area=self.instance
            )

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if instance.pk:
            # Clear previous mapping
            ZipLocation.objects.filter(service_area=instance).update(service_area=None)
            # Assign selected ZIPs to this county
            selected_zips = self.cleaned_data.get("zip_codes")
            if selected_zips:
                selected_zips.update(service_area=instance)
        return instance


@admin.register(ServiceArea)
class ServiceAreaAdmin(admin.ModelAdmin):
    form = ServiceAreaForm

    list_display = (
        "name",
        "is_active",
        "allow_pool_installs",
        "allow_accessory_installs",
        "permit_pool_fee_base",
        "permit_pool_labor_hours",
    )
    list_filter = (
        "is_active",
        "allow_pool_installs",
        "allow_accessory_installs",
    )
    search_fields = ("name",)


@admin.register(ZipLocation)
class ZipLocationAdmin(admin.ModelAdmin):
    list_display = (
        "zip_code",
        "city",
        "county",
        "state",
        "service_area",
        "install_allowed",
    )
    list_filter = ("state", "service_area", "install_allowed")
    search_fields = ("zip_code", "city", "county")



# =======================
# POOL TYPE
# =======================

@admin.register(PoolType)
class PoolTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")
    ordering = ("name",)


# =======================
# POOL MODEL FAMILY
# =======================

class PoolModelFamilyAdminForm(forms.ModelForm):
    class Meta:
        model = PoolModelFamily
        fields = "__all__"
        widgets = {
            "pool_types": forms.CheckboxSelectMultiple,
        }


@admin.register(PoolModelFamily)
class PoolModelFamilyAdmin(admin.ModelAdmin):
    form = PoolModelFamilyAdminForm

    list_display = (
        "name",
        "brand",
        "pool_types_list",
        "quality_label",
        "supports_custom_depth",
        "salt_compatibility",
        "ionizer_compatibility",
    )
    list_filter = (
        "brand",
        "supports_custom_depth",
        "salt_compatibility",
        "ionizer_compatibility",
        "pool_types",
    )
    search_fields = ("name", "brand", "quality_label")
    filter_horizontal = ("pool_types",)


# =======================
# POOL VARIANT & COMPONENTS
# =======================

class PoolPackageComponentInline(admin.TabularInline):
    model = PoolPackageComponent
    extra = 1
    autocomplete_fields = ("item",)


@admin.register(PoolVariant)
class PoolVariantAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "family",
        "shape",
        "size_label",
        "variant_price",
        "shipping_group",
        "install_days",
        "install_daily_rate",
        "is_active",
    )
    list_filter = (
        "shape",
        "family__pool_types",
        "shipping_group",
        "is_active",
    )
    search_fields = ("family__name", "sku", "depth_label")
    inlines = [PoolPackageComponentInline]


# =======================
# ORDERS & ORDER ITEMS
# =======================

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = (
        "pool_variant",
        "store_item",
        "quantity",
        "unit_price",
        "line_subtotal",
        "install_selected",
        "line_install_amount",
        "line_shipping_amount",
        "config_json",
        "added_at",
    )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "status",
        "full_name",
        "email",
        "county_display",   # uses the method on the model we just defined
        "zip_code",
        "created_at",
        "grand_total",
    ]

    readonly_fields = [
        "status",
        "created_at",
        "updated_at",
        "subtotal",
        "shipping_total",
        "install_total",
        "permit_total",
        "tax_total",
        "grand_total",
        "county_display",
    ]

    ordering = ["-created_at"]

    list_filter = ["status"]

    search_fields = ["id", "full_name", "email", "zip_code"]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "order",
        "display_name",
        "quantity",
        "unit_price",
        "line_subtotal",
        "line_install_amount",
        "line_shipping_amount",
    ]
    search_fields = ["order__id", "pool_variant__family__name", "store_item__name"]