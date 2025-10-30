import logging
import json
import os
import smtplib
from datetime import datetime
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection, EmailMessage
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


FAILED_EMAILS_LOG = os.path.join(getattr(settings, "BASE_DIR", "."), "failed_emails.log")


def _persist_failed_email(record: dict):
    """
    Append a JSON line describing a failed email to FAILED_EMAILS_LOG for later inspection/retry.
    """
    try:
        os.makedirs(os.path.dirname(FAILED_EMAILS_LOG), exist_ok=True)
        with open(FAILED_EMAILS_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("Unable to persist failed email record")


def _send_mail_html_subject(subject: str, to: list, template_html: str, context: dict, from_email: str = None):
    """
    Render HTML template and send an email with text fallback.

    Behavior:
    - Returns True on success, False on failure.
    - On SMTPDataError or other SMTPException, logs the SMTP response and (if DEBUG) writes the message to the console fallback.
    - Persists a record of failures to failed_emails.log for later retry.
    """
    if not from_email:
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", getattr(settings, "EMAIL_HOST_USER", None))

    try:
        html_content = render_to_string(template_html, context)
        text_content = strip_tags(html_content)

        # Use configured connection (respects EMAIL_BACKEND)
        connection = get_connection(fail_silently=False)
        msg = EmailMultiAlternatives(subject=subject, body=text_content, from_email=from_email, to=to, connection=connection)
        msg.attach_alternative(html_content, "text/html")

        sent_count = msg.send(fail_silently=False)
        if sent_count:
            logger.debug("Sent email '%s' to %s", subject, to)
            return True

        logger.warning("Email '%s' to %s returned sent_count=%s", subject, to, sent_count)
        return False

    except smtplib.SMTPDataError as e:
        # e.smtp_code, e.smtp_error often contain the server response (e.g., Gmail 451)
        logger.warning(
            "SMTPDataError sending email '%s' to %s: smtp_code=%s smtp_error=%s",
            subject, to, getattr(e, "smtp_code", None), getattr(e, "smtp_error", None)
        )

        # Persist enough info for retry later
        _persist_failed_email({
            "when": datetime.utcnow().isoformat() + "Z",
            "type": "SMTPDataError",
            "subject": subject,
            "to": to,
            "template": template_html,
            "context_keys": list(context.keys()),
            "smtp_code": getattr(e, "smtp_code", None),
            "smtp_error": getattr(e, "smtp_error", None),
        })

        # DEV fallback: print to console backend so developer can see message during runserver
        if getattr(settings, "DEBUG", False):
            try:
                console_conn = get_connection("django.core.mail.backends.console.EmailBackend")
                console_msg = EmailMessage(subject=subject, body=text_content, from_email=from_email, to=to, connection=console_conn)
                console_msg.send()
                logger.debug("Console fallback: wrote email to stdout for '%s' to %s", subject, to)
            except Exception:
                logger.exception("Console fallback failed for '%s' to %s", subject, to)
        return False

    except smtplib.SMTPException as e:
        logger.exception("SMTPException sending email '%s' to %s: %s", subject, to, e)
        _persist_failed_email({
            "when": datetime.utcnow().isoformat() + "Z",
            "type": "SMTPException",
            "subject": subject,
            "to": to,
            "template": template_html,
            "context_keys": list(context.keys()),
            "error": str(e),
        })
        return False

    except Exception as exc:
        logger.exception("Unexpected error sending email '%s' to %s: %s", subject, to, exc)
        _persist_failed_email({
            "when": datetime.utcnow().isoformat() + "Z",
            "type": "Exception",
            "subject": subject,
            "to": to,
            "template": template_html,
            "context_keys": list(context.keys()),
            "error": str(exc),
        })
        return False


# High-level helpers used by views (unchanged interface)
def send_order_placed(order):
    engineer_email = None
    supplier_email = None

    try:
        engineer_email = getattr(order.engineer.user, "email", None)
    except Exception:
        engineer_email = None

    try:
        if hasattr(order.supplier, "profile") and getattr(order.supplier.profile, "user", None):
            supplier_email = getattr(order.supplier.profile.user, "email", None)
        else:
            supplier_email = getattr(order.supplier, "email", None)
    except Exception:
        supplier_email = None

    context = {
        "order": order,
        "material": getattr(order, "material", None),
        "engineer": getattr(order, "engineer", None),
        "supplier": getattr(order, "supplier", None),
        "site_name": getattr(settings, "SITE_NAME", "BuildHub Kenya"),
    }

    sent_any = False
    if engineer_email:
        sent_any = _send_mail_html_subject(
            subject=f"[{context['site_name']}] Order placed — #{order.id}",
            to=[engineer_email],
            template_html="emails/order_placed.html",
            context={**context, "recipient": "engineer"},
        ) or sent_any

    if supplier_email and supplier_email != engineer_email:
        sent_any = _send_mail_html_subject(
            subject=f"[{context['site_name']}] New order received — #{order.id}",
            to=[supplier_email],
            template_html="emails/order_placed.html",
            context={**context, "recipient": "supplier"},
        ) or sent_any

    return sent_any


def send_order_dispatched(delivery):
    order = getattr(delivery, "order", None)
    if not order:
        return False

    engineer_email = getattr(order.engineer.user, "email", None) if getattr(order, "engineer", None) else None

    context = {
        "delivery": delivery,
        "order": order,
        "material": getattr(order, "material", None),
        "site_name": getattr(settings, "SITE_NAME", "BuildHub Kenya"),
    }

    sent = False
    if engineer_email:
        sent = _send_mail_html_subject(
            subject=f"[{context['site_name']}] Your order #{order.id} is dispatched",
            to=[engineer_email],
            template_html="emails/order_dispatched.html",
            context=context,
        ) or sent
    return sent


def send_order_delivered(delivery):
    order = getattr(delivery, "order", None)
    if not order:
        return False

    engineer_email = getattr(order.engineer.user, "email", None) if getattr(order, "engineer", None) else None

    context = {
        "delivery": delivery,
        "order": order,
        "material": getattr(order, "material", None),
        "site_name": getattr(settings, "SITE_NAME", "BuildHub Kenya"),
    }

    sent = False
    if engineer_email:
        sent = _send_mail_html_subject(
            subject=f"[{context['site_name']}] Your order #{order.id} has been delivered",
            to=[engineer_email],
            template_html="emails/order_delivered.html",
            context=context,
        ) or sent
    return sent