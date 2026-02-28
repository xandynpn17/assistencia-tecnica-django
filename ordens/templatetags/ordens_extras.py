from django import template


register = template.Library()


@register.filter
def decode_escaped_newlines(value):
    if value is None:
        return ""
    return str(value).replace("\\n", "\n")

