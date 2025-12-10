from django.urls import path
from . import views
from store import views as store_views
from django.contrib import admin
from django.urls import path, include


app_name = "store"

urlpatterns = [
    path("", views.builder_page, name="builder_page"),
    path("", views.home, name="home"),

    path("api/builder/zip-check/", views.builder_zip_check, name="builder_zip_check"),
    path("api/builder/pools/", views.builder_pool_options, name="builder_pool_options"),
    path("api/builder/pool/<int:variant_id>/components/", views.builder_pool_components, name="builder_pool_components"),

    path("api/cart/add-item/", views.cart_add_item, name="cart_add_item"),
    path("api/cart/", views.cart_summary, name="cart_summary"),
    path("api/cart/item/<int:item_id>/", views.cart_item_update_delete, name="cart_item_update_delete"),
    path("api/cart/item/<int:item_id>/remove/", views.cart_remove_item, name="cart_remove_item"),
    path("api/cart/update-zip/", views.cart_update_zip, name="cart_update_zip"),
    path("api/cart/checkout/", views.cart_checkout, name="cart_checkout"),
    path("api/cart/item/<int:item_id>/configure/", views.cart_configure_item, name="cart_configure_item"),
    path("api/cart/summary/", views.cart_summary, name="cart_summary"),
    path("api/order/<int:order_id>/summary/", views.order_summary, name="order_summary"),
]








