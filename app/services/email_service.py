import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Content, Email, Mail, To

from app.core.config import settings


class EmailDeliveryError(Exception):
    pass


def _send_via_console(to_email: str, subject: str, text_body: str, html_body: str | None) -> None:
    print("=== EMAIL (console provider) ===")
    print(f"To: {to_email}")
    print(f"Subject: {subject}")
    print("Body:")
    print(text_body)
    if html_body:
        print("HTML:")
        print(html_body)
    print("=== END EMAIL ===")


def _send_via_smtp(to_email: str, subject: str, text_body: str, html_body: str | None) -> None:
    if not settings.smtp_host:
        raise EmailDeliveryError("SMTP host is not configured")

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = settings.email_from
    message["To"] = to_email
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        message.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if settings.smtp_use_ssl:
            client = smtplib.SMTP_SSL(
                host=settings.smtp_host,
                port=settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
            )
        else:
            client = smtplib.SMTP(
                host=settings.smtp_host,
                port=settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
            )

        with client:
            if settings.smtp_starttls and not settings.smtp_use_ssl:
                client.starttls()
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password)
            client.sendmail(settings.email_from, [to_email], message.as_string())
    except Exception as exc:
        raise EmailDeliveryError(str(exc)) from exc


def _send_via_sendgrid(to_email: str, subject: str, text_body: str, html_body: str | None) -> None:
    if not settings.sendgrid_api_key:
        raise EmailDeliveryError("SENDGRID_API_KEY is not configured")

    message = Mail(
        from_email=Email(settings.email_from),
        to_emails=To(to_email),
        subject=subject,
    )
    message.add_content(Content("text/plain", text_body))
    if html_body:
        message.add_content(Content("text/html", html_body))

    try:
        client = SendGridAPIClient(settings.sendgrid_api_key)
        response = client.send(message)
        if response.status_code >= 400:
            raise EmailDeliveryError(f"SendGrid error status: {response.status_code}")
    except Exception as exc:
        raise EmailDeliveryError(str(exc)) from exc


def send_email(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    if settings.email_provider == "console":
        _send_via_console(to_email, subject, text_body, html_body)
        return
    if settings.email_provider == "smtp":
        _send_via_smtp(to_email, subject, text_body, html_body)
        return
    if settings.email_provider == "sendgrid":
        _send_via_sendgrid(to_email, subject, text_body, html_body)
        return
    raise EmailDeliveryError(f"Unsupported EMAIL_PROVIDER: {settings.email_provider}")


def build_verification_message(token: str) -> tuple[str, str]:
    verify_url = f"{settings.frontend_base_url.rstrip('/')}/verify-email?token={token}"
    subject = "Verify your email address"
    text = (
        "Welcome.\n\n"
        f"Use this verification link: {verify_url}\n\n"
        f"If needed, you can use this code as token: {token}\n"
    )
    html = (
        "<p>Welcome.</p>"
        f"<p>Verify your email by clicking <a href=\"{verify_url}\">this link</a>.</p>"
        f"<p>If needed, use this token: <code>{token}</code></p>"
    )
    return subject, text, html


def build_password_reset_message(token: str) -> tuple[str, str]:
    reset_url = f"{settings.frontend_base_url.rstrip('/')}/reset-password?token={token}"
    subject = "Password reset request"
    text = (
        "We received a password reset request.\n\n"
        f"Use this reset link: {reset_url}\n\n"
        f"If needed, you can use this code as token: {token}\n"
    )
    html = (
        "<p>We received a password reset request.</p>"
        f"<p>Reset your password using <a href=\"{reset_url}\">this link</a>.</p>"
        f"<p>If needed, use this token: <code>{token}</code></p>"
    )
    return subject, text, html
