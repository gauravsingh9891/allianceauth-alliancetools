from . import urls
from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook


class AllianceMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(self, 'Alliance Toolbox',
                              'fa fa-empire fa-fw',
                              'alliancetools:dashboard',
                              navactive=['alliancetools:'])

    def render(self, request):
        if request.user.has_perm('alliancetools.access_alliance_tools'):
            return MenuItemHook.render(self, request)
        return ''


@hooks.register('menu_item_hook')
def register_menu():
    return AllianceMenu()


@hooks.register('url_hook')
def register_url():
    return UrlHook(urls, 'alliancetools', r'^alliancetools/')
