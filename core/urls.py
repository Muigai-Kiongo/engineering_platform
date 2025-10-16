from django.urls import path
from . import views

urlpatterns = [
    path('', views.role_redirect, name='role_redirect'),


    # Engineer routes
    path('dashboard/', views.engineer_dashboard, name='engineer_dashboard'),
    path('materials/', views.material_list, name='material_list'),
    path('materials/<int:pk>/', views.material_detail, name='material_detail'),
    path('order/<int:material_id>/place/', views.place_order, name='place_order'),
    path('orders/', views.order_list, name='order_list'),
    path('orders/<int:order_id>/', views.order_detail, name='order_detail'),
    path('supplier/<int:supplier_id>/review/', views.review_supplier, name='review_supplier'),

    # Supplier routes
    path('supplier/dashboard/', views.supplier_dashboard, name='supplier_dashboard'),
    path('supplier/orders/', views.supplier_orders, name='supplier_orders'),
    path('supplier/materials/', views.supplier_materials, name='supplier_materials'),
    path('supplier/materials/<int:pk>/', views.supplier_material_detail, name='supplier_material_detail'),
    path('supplier/add-material/', views.supplier_add_material, name='supplier_add_material'),
    path('supplier/profile/', views.supplier_profile, name='supplier_profile'),
    path('supplier/reviews/', views.supplier_reviews, name='supplier_reviews'),
]