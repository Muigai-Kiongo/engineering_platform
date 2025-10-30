"""
Reporting views for the core app.

Provides:
- Engineer reports (engineer dashboard + CSV export)
- Supplier reports (supplier dashboard + CSV export)
- Delivery agent reports (delivery dashboard + CSV export)

Design:
- Each report accepts optional GET params: start_date, end_date (YYYY-MM-DD) and format=csv
- HTML pages render KPIs + short tables; ?format=csv returns a CSV attachment
- Reuses existing role decorators (engineer_only, supplier_only, delivery_only)
"""
from typing import Optional, Tuple
import csv
import io
from datetime import datetime, timedelta

from django.shortcuts import render
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils import timezone
from django.db.models import Sum, Count
from django.conf import settings
from django.urls import reverse

from .models import Order, Material, Delivery, SupplierReview
from .views import engineer_only, supplier_only, delivery_only  # reuse decorators
from .models import SupplierProfile

DATE_FORMAT = "%Y-%m-%d"


def _parse_date_range(request) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Parse start_date and end_date from GET parameters.
    Returns (start_dt, end_dt) as timezone-aware datetimes or (None, None).
    """
    start = request.GET.get("start_date")
    end = request.GET.get("end_date")
    start_dt = None
    end_dt = None
    try:
        if start:
            start_dt = datetime.strptime(start, DATE_FORMAT)
            start_dt = timezone.make_aware(datetime.combine(start_dt.date(), datetime.min.time()))
        if end:
            end_dt = datetime.strptime(end, DATE_FORMAT)
            # include the entire day
            end_dt = timezone.make_aware(datetime.combine(end_dt.date(), datetime.max.time()))
    except Exception:
        # invalid date format
        return None, None
    return start_dt, end_dt


def _in_date_range(qs, start_dt, end_dt):
    if start_dt:
        qs = qs.filter(created_at__gte=start_dt)
    if end_dt:
        qs = qs.filter(created_at__lte=end_dt)
    return qs


@engineer_only
def engineer_report(request):
    """
    Engineer-facing report showing orders placed by the current engineer.
    Supports CSV export via ?format=csv
    """
    profile = request.user.profile
    start_dt, end_dt = _parse_date_range(request)
    if start_dt is None and request.GET.get("start_date"):
        return HttpResponseBadRequest("Invalid start_date, expected YYYY-MM-DD")

    orders_qs = Order.objects.filter(engineer=profile).select_related("material", "supplier").order_by("-created_at")
    orders_qs = _in_date_range(orders_qs, start_dt, end_dt)

    total_orders = orders_qs.count()
    total_spent = orders_qs.aggregate(total=Sum("total_price"))["total"] or 0

    top_suppliers = (
        orders_qs.values("supplier__company_name")
        .annotate(count=Count("id"), sales=Sum("total_price"))
        .order_by("-count")[:10]
    )

    top_materials = (
        orders_qs.values("material__name")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    recent = orders_qs[:50]

    # CSV export
    if request.GET.get("format") == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Order ID", "Material", "Supplier", "Quantity", "Total Price", "Status", "Created At"])
        for o in recent:
            writer.writerow([
                o.id,
                getattr(o.material, "name", ""),
                getattr(o.supplier, "company_name", "") or getattr(getattr(o.supplier, "profile", None), "user", None) and getattr(o.supplier.profile.user, "username", ""),
                o.quantity,
                o.total_price,
                getattr(o, "status", ""),
                o.created_at.isoformat() if o.created_at else "",
            ])
        resp = HttpResponse(buf.getvalue(), content_type="text/csv")
        fname = f"engineer_report_{profile.pk}_{timezone.now().strftime('%Y%m%d%H%M')}.csv"
        resp["Content-Disposition"] = f'attachment; filename="{fname}"'
        return resp

    context = {
        "profile": profile,
        "total_orders": total_orders,
        "total_spent": total_spent,
        "top_suppliers": top_suppliers,
        "top_materials": top_materials,
        "recent": recent,
        "start_date": request.GET.get("start_date", ""),
        "end_date": request.GET.get("end_date", ""),
        "csv_url": f"{reverse('engineer_report')}?{request.GET.urlencode()}" if request.GET else f"{reverse('engineer_report')}?format=csv",
    }
    return render(request, "reports/engineer_report.html", context)


@supplier_only
def supplier_report(request):
    """
    Supplier-facing report showing KPIs for the supplier profile linked to the user.
    Supports CSV export via ?format=csv
    """
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        return HttpResponseBadRequest("Supplier profile not found")

    start_dt, end_dt = _parse_date_range(request)
    if start_dt is None and request.GET.get("start_date"):
        return HttpResponseBadRequest("Invalid start_date, expected YYYY-MM-DD")

    orders_qs = Order.objects.filter(supplier=supplier_profile).select_related("material", "engineer").order_by("-created_at")
    orders_qs = _in_date_range(orders_qs, start_dt, end_dt)

    materials_qs = Material.objects.filter(supplier=supplier_profile)
    materials_count = materials_qs.count()

    orders_count = orders_qs.count()
    total_sales = orders_qs.aggregate(total=Sum("total_price"))["total"] or 0

    top_engineers = (
        orders_qs.values("engineer__user__username")
        .annotate(count=Count("id"), spend=Sum("total_price"))
        .order_by("-count")[:10]
    )

    recent_orders = orders_qs[:50]

    if request.GET.get("format") == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Order ID", "Engineer", "Material", "Qty", "Total", "Status", "Created At"])
        for o in recent_orders:
            writer.writerow([
                o.id,
                getattr(o.engineer.user, "username", ""),
                getattr(o.material, "name", ""),
                o.quantity,
                o.total_price,
                getattr(o, "status", ""),
                o.created_at.isoformat() if o.created_at else "",
            ])
        resp = HttpResponse(buf.getvalue(), content_type="text/csv")
        fname = f"supplier_report_{supplier_profile.pk}_{timezone.now().strftime('%Y%m%d%H%M')}.csv"
        resp["Content-Disposition"] = f'attachment; filename="{fname}"'
        return resp

    context = {
        "supplier": supplier_profile,
        "materials_count": materials_count,
        "orders_count": orders_count,
        "total_sales": total_sales,
        "top_engineers": top_engineers,
        "recent_orders": recent_orders,
        "start_date": request.GET.get("start_date", ""),
        "end_date": request.GET.get("end_date", ""),
    }
    return render(request, "reports/supplier_report.html", context)


@delivery_only
def delivery_agent_report(request):
    """
    Delivery agent report: shows assigned deliveries and activity.
    Supports CSV export via ?format=csv
    """
    agent_profile = request.user.profile
    start_dt, end_dt = _parse_date_range(request)
    if start_dt is None and request.GET.get("start_date"):
        return HttpResponseBadRequest("Invalid start_date, expected YYYY-MM-DD")

    deliveries_qs = Delivery.objects.filter(delivery_agent=agent_profile).select_related("order__material", "order__engineer").order_by("-id")
    if start_dt:
        deliveries_qs = deliveries_qs.filter(created_at__gte=start_dt) if hasattr(Delivery, "created_at") else deliveries_qs
    if end_dt:
        deliveries_qs = deliveries_qs.filter(created_at__lte=end_dt) if hasattr(Delivery, "created_at") else deliveries_qs

    total_assigned = deliveries_qs.count()
    delivered = deliveries_qs.filter(delivered_at__isnull=False).count()
    dispatched = deliveries_qs.filter(dispatched_at__isnull=False).count()
    in_transit = deliveries_qs.filter(dispatched_at__isnull=False, delivered_at__isnull=True).count()
    pending = deliveries_qs.filter(dispatched_at__isnull=True).count()

    recent = deliveries_qs[:100]

    if request.GET.get("format") == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Delivery ID", "Order ID", "Material", "Status", "Dispatched At", "Delivered At", "Delivery Location"])
        for d in recent:
            status = "delivered" if d.delivered_at else ("in_transit" if d.dispatched_at else "pending")
            writer.writerow([
                d.id,
                getattr(d.order, "id", ""),
                getattr(getattr(d.order, "material", None), "name", ""),
                status,
                d.dispatched_at.isoformat() if getattr(d, "dispatched_at", None) else "",
                d.delivered_at.isoformat() if getattr(d, "delivered_at", None) else "",
                getattr(d, "delivery_location", ""),
            ])
        resp = HttpResponse(buf.getvalue(), content_type="text/csv")
        fname = f"delivery_report_{agent_profile.pk}_{timezone.now().strftime('%Y%m%d%H%M')}.csv"
        resp["Content-Disposition"] = f'attachment; filename="{fname}"'
        return resp

    context = {
        "agent_profile": agent_profile,
        "total_assigned": total_assigned,
        "delivered": delivered,
        "dispatched": dispatched,
        "in_transit": in_transit,
        "pending": pending,
        "recent": recent,
        "start_date": request.GET.get("start_date", ""),
        "end_date": request.GET.get("end_date", ""),
    }
    return render(request, "reports/delivery_report.html", context)