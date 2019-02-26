from django.template.defaulttags import register
from ..models import ItemName, TypeName, BridgeOzoneLevel


@register.filter
def item_name(item_id):
    try:
        name = ItemName.objects.get(item_id=item_id).name
        return name
    except:
        return item_id


@register.filter
def type_name(type_id):
    try:
        name = TypeName.objects.get(type_id=type_id).name
        return name
    except:
        return type_id


@register.filter(name='deslug')
def deslug(input):
    try:
        return input.replace('_', ' ')
    except:
        return input


@register.filter(name='slug_dl')
def slug_dl(input):
    try:
        return input.replace(' ', '_')
    except:
        return input

@register.filter(name='reinf_day')
def reinf_day(input):
    if input == 0:
        return "Monday"
    elif input == 1:
        return "Tuesday"
    elif input == 2:
        return "Wednesday"
    elif input == 3:
        return "Thursday"
    elif input == 4:
        return "Friday"
    elif input == 5:
        return "Saturday"
    elif input == 6:
        return "Sunday"
    else:
        return "N/A"


@register.filter(name='item_image')
def item_image(type_id):
    try:
        name = TypeName.objects.get(type_id=type_id).name
        return "<img class=\"img-rounded\" src=\"https://imageserver.eveonline.com/Type/%s_32.png\" style=\"height: 32px; width: 32px;\" title=\"%s\">" % (int(type_id), name)
    except:
        return ""


@register.filter(name='addclass')
def addclass(value, arg):
    return value.as_widget(attrs={'class': arg})
