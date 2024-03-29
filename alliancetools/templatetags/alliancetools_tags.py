from django.template.defaulttags import register
from ..models import ItemName, TypeName, BridgeOzoneLevel
import logging
from django.utils.safestring import mark_safe


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


@register.filter()
def standing_span(standing):
    try:

        if standing > 0:
            if standing <= 5:
                return mark_safe('<span class="label label-info">{}</span>'.format(standing))
            else:
                return mark_safe('<span class="label label-primary">{}</span>'.format(standing))
        elif standing < 0:
            if standing >= -5:
                return mark_safe('<spam class="label label-warning">{}</span>'.format(standing))
            else:
                return mark_safe('<span class="label label-danger">{}</span>'.format(standing))
        else:
            return mark_safe('<span class="label label-default">{}</span>'.format(standing))

    except:
        #logging.exception("Messsage")
        return ""


@register.simple_tag()
def evename_img(_id, name, cat, size):
    cats = {'character': 'Character', 'corporation': 'Corporation', 'alliance': 'Alliance'}
    fmt = 'png'
    if cat == 'character':
        fmt = 'jpg'
    if cat in cats:
        return mark_safe('<img class="img-circle" src="https://imageserver.eveonline.com/%s/%s_128.%s"'
                         ' style="height: %spx; width: %spx;" title="%s">' % (cats[cat], _id, fmt, size, size, name))

    else:
        return ""


@register.filter()
def ore_color(ore):
    try:
        if 'Bitumens' in ore or 'Coesite' in ore or 'Sylvite' in ore or 'Zeolite' in ore:
            return mark_safe('style="background-color:#9B1C31"')
        elif 'Cobalite' in ore or 'Euxenite' in ore or 'Scheelite' in ore or 'Titanite' in ore:
            return mark_safe('style="background-color:#E86100"')
        elif 'Chromite' in ore or 'Otavite' in ore or 'Sperrylite' in ore or 'Vanadinite' in ore:
            return mark_safe('style="background-color:#FFAA1D"')
        elif 'Carnotite' in ore or 'Cinnabar' in ore or 'Pollucite' in ore or 'Zircon' in ore:
            return mark_safe('style="background-color:#4B8B3B"')
        elif 'Loparite' in ore or 'Monazite' in ore or 'Xenotime' in ore or 'Ytterbite' in ore:
            return mark_safe('style="background-color:#0D98BA"')
        else:
            return mark_safe('style="background-color:#B57EDC"')

    except:
        #logging.exception("Messsage")
        return ""

