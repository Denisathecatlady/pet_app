"""Password validators."""

from django.contrib.auth import password_validation


class MinimumLengthValidator(password_validation.MinimumLengthValidator):
    """Django's minimum length validator with a Czech error message.

    Django 5.2.18 raises this message with a msgid that its Czech catalogue does not
    contain, so without this subclass the error would be shown in English.
    """

    def get_error_message(self) -> str:
        count = self.min_length
        unit = "znak" if count == 1 else "znaky" if 2 <= count <= 4 else "znaků"
        return f"Heslo je příliš krátké. Musí mít alespoň {count} {unit}."
