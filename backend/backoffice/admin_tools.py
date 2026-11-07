"""Small helpers shared by the admins of the application (docs/14).

* :func:`status_badge`: a status in a list as icon + text + colour (never colour alone);
* :func:`action_confirmed` and :func:`confirmation_response`: the intermediate page of an
  administration action, built like Django's own *delete selected* (the first POST shows the
  page, the POST with ``post=yes`` carries it out).
"""

import enum
from collections.abc import Iterable
from typing import Any

from django.contrib.admin import ModelAdmin, helpers
from django.db.models import Model
from django.http import HttpRequest
from django.template.response import TemplateResponse
from django.utils.html import format_html
from django.utils.safestring import SafeString

CONFIRMED_FIELD = "post"


class Tone(enum.Enum):
    """The colour of a status (CSS classes ``barf-status--<value>`` in static/css/admin.css)."""

    SUCCESS = "success"
    INFO = "info"
    WARNING = "warning"
    DANGER = "danger"


def status_badge(tone: Tone, icon: str, label: str) -> SafeString:
    """Return a status for a list or a detail page: an icon (hidden from screen readers), the
    text and the colour of ``tone``. The text is what carries the meaning; it is escaped."""
    return format_html(
        '<span class="barf-status barf-status--{}"><span aria-hidden="true">{}</span> {}</span>',
        tone.value,
        icon,
        label,
    )


def action_confirmed(request: HttpRequest) -> bool:
    """Return whether this POST is the confirmation of an action (the page was submitted)."""
    return request.method == "POST" and request.POST.get(CONFIRMED_FIELD) == "yes"


def confirmation_response(
    modeladmin: ModelAdmin,
    request: HttpRequest,
    selected: Iterable[Model],
    *,
    action: str,
    template: str,
    title: str,
    context: dict[str, Any] | None = None,
) -> TemplateResponse:
    """Render the confirmation page of an action on the selected records.

    Inputs: the admin, the request, the selected records (all of them: the page posts their
    keys back), the name of the action (the function
    name, posted back as ``action``), the template (it extends
    ``admin/accounts/confirm_action.html``), its title and the template's own context. The page
    carries the selected keys and ``post=yes`` back to the list, which calls the action again.
    """
    full_context = {
        **modeladmin.admin_site.each_context(request),
        "title": title,
        "subtitle": None,
        "opts": modeladmin.model._meta,
        "selected": list(selected),
        "action_name": action,
        "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
        "cancel_url": request.get_full_path(),
        **(context or {}),
    }
    return TemplateResponse(request, template, full_context)
