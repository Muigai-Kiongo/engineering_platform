from django.urls import path
from . import views
from . import reports

urlpatterns = [
    path('', views.role_redirect, name='role_redirect'),

    # Notifications
    path('notifications/', views.notifications, name='notifications'),

    # Engineer routes
    path('dashboard/', views.engineer_dashboard, name='engineer_dashboard'),
    path('materials/', views.material_list, name='material_list'),
    path('materials/<int:pk>/', views.material_detail, name='material_detail'),
    path('order/<int:material_id>/place/', views.place_order, name='place_order'),
    path('orders/', views.order_list, name='order_list'),
    path('orders/<int:order_id>/', views.order_detail, name='order_detail'),
    path('orders/<int:order_id>/cancel/', views.cancel_order, name='cancel_order'),
    path('supplier/<int:supplier_id>/review/', views.review_supplier, name='review_supplier'),

    # Delivery agent routes
    path('delivery/dashboard/', views.delivery_agent_dashboard, name='delivery_dashboard'),
    path('delivery/', views.deliveries_list, name='deliveries_list'),
    path('delivery/<int:pk>/', views.delivery_detail, name='delivery_detail'),
    path('delivery/<int:pk>/update/', views.delivery_update_status, name='delivery_update_status'),

    # Supplier routes
    path('supplier/dashboard/', views.supplier_dashboard, name='supplier_dashboard'),
    path('supplier/orders/', views.supplier_orders, name='supplier_orders'),
    path('supplier/materials/', views.supplier_materials, name='supplier_materials'),
    path('supplier/materials/<int:pk>/', views.supplier_material_detail, name='supplier_material_detail'),
    path('supplier/add-material/', views.supplier_add_material, name='supplier_add_material'),
     path('supplier/materials/<int:pk>/edit/', views.supplier_edit_material, name='supplier_edit_material'),
    path('supplier/materials/<int:pk>/delete/', views.supplier_delete_material, name='supplier_delete_material'),
    path('supplier/profile/', views.supplier_profile, name='supplier_profile'),
    path('supplier/reviews/', views.supplier_reviews, name='supplier_reviews'),

    # Reports
    path("reports/engineer/", reports.engineer_report, name="engineer_report"),
    path("reports/supplier/", reports.supplier_report, name="supplier_report"),
    path("reports/delivery/", reports.delivery_agent_report, name="delivery_report"),
]