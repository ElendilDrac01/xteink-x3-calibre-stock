from calibre.customize import InterfaceActionBase


class XteinkX3Plugin(InterfaceActionBase):

    name = "Xteink X3"

    description = (
        "Envoyer des livres vers un Xteink X3 "
        "par WiFi local"
    )

    supported_platforms = [
        "linux",
        "windows",
        "osx"
    ]

    author = "Xteink community"

    version = (0, 1, 0)

    actual_plugin = (
        "calibre_plugins.xteink_x3.action:"
        "XteinkX3Action"
    )
