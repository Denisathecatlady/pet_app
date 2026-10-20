"""Template filters for rendering forms (core/includes/form_fields.html)."""

from django import template
from django.forms import BaseForm

register = template.Library()


@register.filter
def has_field_errors(form: BaseForm) -> bool:
    """Return whether a visible field of ``form`` has an error (not only non-field errors)."""
    return any(field.errors for field in form.visible_fields())
