from esi.models import Token
from esi.clients import TokenAuthenticator, CachingHttpFuture
from bravado.client import SwaggerClient, CONFIG_DEFAULTS
from bravado.swagger_model import Loader
from bravado import requests_client
from esi import app_settings
from django.core.cache import cache
from bravado_core.spec import Spec
import json

try:
    import urlparse
except ImportError:  # py3
    from urllib import parse as urlparse


SPEC_CONFIG = {'use_models': False}


requests_client.HttpFuture = CachingHttpFuture


def build_cache_name(name):
    """
    Cache key name formatter
    :param name: Name of the spec dict to cache, usually version
    :return: String name for cache key
    :rtype: str
    """
    return 'esi_swaggerspec_%s' % name


def cache_spec(name, spec):
    """
    Cache the spec dict
    :param name: Version name
    :param spec: Spec dict
    :return: True if cached
    """
    return cache.set(build_cache_name(name), spec, app_settings.ESI_SPEC_CACHE_DURATION)


def build_spec_url(spec_version):
    """
    Generates the URL to swagger.json for the ESI version
    :param spec_version: Name of the swagger spec version, like latest or v4
    :return: URL to swagger.json for the requested spec version
    """
    return urlparse.urljoin(app_settings.ESI_API_URL, spec_version + '/swagger.json')


def read_spec(path, config=None, http_client=None):
    """
    Reads in a swagger spec file used to initialize a SwaggerClient
    :param path: String path to local swagger spec file.
    :param http_client: :class:`bravado.requests_client.RequestsClient`
    :param config: Bravado config.
    :return: :class:`bravado_core.spec.Spec`
    """
    with open(path, 'r') as f:
        spec_dict = json.loads(f.read())

    return SwaggerClient.from_spec(spec_dict, http_client=http_client, config=config)


def get_spec(name, http_client=None, config=None):
    """
    :param name: Name of the revision of spec, eg latest or v4
    :param http_client: Requests client used for retrieving specs
    :param config: Spec configuration - see Spec.CONFIG_DEFAULTS
    :return: :class:`bravado_core.spec.Spec`
    """
    http_client = http_client or requests_client.RequestsClient()

    def load_spec():
        loader = Loader(http_client)
        return loader.load_spec(build_spec_url(name))

    spec_dict = cache.get_or_set(build_cache_name(name), load_spec, app_settings.ESI_SPEC_CACHE_DURATION)
    config = dict(CONFIG_DEFAULTS, **(config or {}))
    return Spec.from_dict(spec_dict, build_spec_url(name), http_client, config)


def build_spec(base_version, response=None, http_client=None, **kwargs):
    """
    Generates the Spec used to initialize a SwaggerClient, supporting mixed resource versions
    :param http_client: :class:`bravado.requests_client.RequestsClient`
    :param base_version: Version to base the spec on. Any resource without an explicit version will be this.
    :param response: Return response?
    :param kwargs: Explicit resource versions, by name (eg Character='v4')
    :return: :class:`bravado_core.spec.Spec`
    """
    config = SPEC_CONFIG
    if response:
        SPEC_CONFIG['also_return_response'] = True

    base_spec = get_spec(name=base_version, http_client=http_client, config=config)
    if kwargs:
        for resource, resource_version in kwargs.items():
            versioned_spec = get_spec(resource_version, http_client=http_client, config=config)
            try:
                spec_resource = versioned_spec.resources[resource.capitalize()]
            except KeyError:
                raise AttributeError(
                    'Resource {0} not found on API revision {1}'.format(resource, resource_version))
            base_spec.resources[resource.capitalize()] = spec_resource
    return base_spec


def esi_client_factory(token=None, datasource=None, spec_file=None, response=None, version=None,  **kwargs):
    """
    Generates an ESI client.
    :param token: :class:`esi.Token` used to access authenticated endpoints.
    :param datasource: Name of the ESI datasource to access.
    :param spec_file: Absolute path to a swagger spec file to load.
    :param version: Base ESI API version. Accepted values are 'legacy', 'latest', 'dev', or 'vX' where X is a number.
    :param response: Return response?
    :param kwargs: Explicit resource versions to build, in the form Character='v4'. Same values accepted as version.
    :return: :class:`bravado.client.SwaggerClient`
    If a spec_file is specified, specific versioning is not available. Meaning the version and resource version kwargs
    are ignored in favour of the versions available in the spec_file.
    """
    config = SPEC_CONFIG
    if response:
        SPEC_CONFIG['also_return_response'] = True

    client = requests_client.RequestsClient()
    if token or datasource:
        client.authenticator = TokenAuthenticator(token=token, datasource=datasource)

    api_version = version or app_settings.ESI_API_VERSION

    if spec_file:
        return read_spec(spec_file, config=config, http_client=client)
    else:
        spec = build_spec(base_version=api_version, response=response, http_client=client, **kwargs)
    if response:
        return SwaggerClient(spec, True)

    return SwaggerClient(spec)


class EsiResponseClient:
    def __init__(self, token):
        self.token = token

    def get_esi_client(self, **kwargs):
        """
        Creates an authenticated ESI client with this token.
        :param kwargs: Extra spec versioning as per `esi.clients.esi_client_factory`
        :return: :class:`bravado.client.SwaggerClient`
        """
        return esi_client_factory(token=self.token, **kwargs)
