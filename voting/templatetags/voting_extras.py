from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Erlaubt dict[key] in Templates: {{ mydict|get_item:key }}"""
    if isinstance(dictionary, dict):
        return dictionary.get(key, 0)
    return 0