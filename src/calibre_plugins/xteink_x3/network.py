import http.client
import json
import mimetypes
import os
import re
import socket
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid


CONFIG_DIR = os.path.expanduser("~/.config/calibre")
CONFIG_FILE = os.path.join(CONFIG_DIR, "xteink_x3.json")


def http_opener():
    # Connexion directe au Xteink sur le LAN.
    # On ignore les éventuels proxies configurés dans l'environnement.
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )


class XteinkError(Exception):
    pass


# ----------------------------------------------------------------------
# Configuration (IP mémorisée + liste d'appareils nommés)
# ----------------------------------------------------------------------

def _load_config():
    """
    Charge le fichier de configuration JSON du plugin dans son
    intégralité, ou {} si absent/invalide.
    """

    try:

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:

            return json.load(f)

    except Exception:

        return {}


def _save_config(data):
    """
    Écrit le fichier de configuration JSON du plugin. Toujours appelé
    avec le contenu complet (voir _load_config) pour ne jamais perdre
    une clé existante au passage.
    """

    try:

        os.makedirs(CONFIG_DIR, exist_ok=True)

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:

            json.dump(
                data,
                f,
                indent=2,
                ensure_ascii=False,
            )

    except Exception as e:

        print(
            "Xteink X3: impossible de sauvegarder la configuration :",
            e,
        )


def load_saved_ip():

    ip = _load_config().get("ip")

    if ip:
        return ip.strip()

    return None


def save_ip(ip):

    # IMPORTANT : on part de la config existante et on la met à jour,
    # plutôt que d'écraser tout le fichier — sans ça, chaque appel à
    # save_ip() effacerait la liste d'appareils nommés (voir
    # load_devices/save_device ci-dessous).
    data = _load_config()

    data["ip"] = ip

    _save_config(data)


def load_devices():
    """
    Retourne la liste des appareils Xteink enregistrés, sous la forme
    [{"name": ..., "ip": ...}, ...].

    Si aucune liste nommée n'existe encore mais qu'une IP unique (ancien
    format à IP unique, avant l'ajout de cette fonctionnalité) est
    mémorisée, elle est présentée comme un unique appareil sans nom
    personnalisé plutôt que perdue.
    """

    data = _load_config()

    devices = data.get("devices")

    if isinstance(devices, list):

        return [
            d for d in devices
            if isinstance(d, dict) and d.get("name") and d.get("ip")
        ]

    old_ip = data.get("ip")

    if old_ip:

        old_ip = old_ip.strip()

        return [
            {
                "name": old_ip,
                "ip": old_ip,
            }
        ]

    return []


def save_device(name, ip):
    """
    Ajoute ou met à jour (par nom) un appareil dans la liste mémorisée.
    """

    data = _load_config()

    devices = data.get("devices")

    if not isinstance(devices, list):
        devices = []

    name = name.strip()
    ip = ip.strip()

    devices = [
        d for d in devices
        if isinstance(d, dict) and d.get("name") != name
    ]

    devices.append(
        {
            "name": name,
            "ip": ip,
        }
    )

    data["devices"] = devices

    _save_config(data)


def delete_device(name):

    data = _load_config()

    devices = data.get("devices")

    if not isinstance(devices, list):
        return

    devices = [
        d for d in devices
        if isinstance(d, dict) and d.get("name") != name
    ]

    data["devices"] = devices

    _save_config(data)


# ----------------------------------------------------------------------
# Initialisation Xteink
# ----------------------------------------------------------------------

def initialize_xteink():
    """
    Appel initial nécessaire pour débloquer l'accès
    à l'interface réseau locale du X3.

    Ce comportement vient du firmware stock Xteink lui-même,
    pas de ce plugin : sans cet appel, /Read_info, /edit et /list
    ne répondent pas sur le LAN. Voir la section "About the
    bofi.xteink.com request" du README pour le détail de ce qui
    est (et n'est pas) envoyé.
    """
    url = "http://bofi.xteink.com/index.html"

    print("Xteink X3: initialisation via", url)

    try:
        with http_opener().open(url, timeout=10) as response:
            response.read()

        print("Xteink X3: initialisation OK")

    except Exception as e:
        raise XteinkError(
            "Impossible d'initialiser la connexion Xteink\n\n%s" % e
        )


# ----------------------------------------------------------------------
# Informations Xteink
# ----------------------------------------------------------------------

# Clés connues dans la réponse de /Read_info, qui se présente comme
# une suite "Clé1:valeur1Clé2:valeur2..." sans séparateur fiable.
INFO_KEYS = (
    "Version",
    "ID",
    "STA-MAC",
    "AP-MAC",
)

# Capture chaque "Clé:valeur", la valeur s'arrêtant juste avant
# la prochaine clé connue ou la fin de la chaîne. Robuste à un
# changement d'ordre des champs ou à l'ajout de nouvelles clés
# (celles-ci seront simplement ignorées au lieu de casser le
# découpage des clés existantes).
INFO_PATTERN = re.compile(
    r"(%s):(.*?)(?=(?:%s):|$)" % (
        "|".join(re.escape(key) for key in INFO_KEYS),
        "|".join(re.escape(key) for key in INFO_KEYS),
    ),
    re.DOTALL,
)


def clean_info_field(info, key, default="?"):
    """
    Récupère un champ d'un dict retourné par get_info() en le
    nettoyant (suppression des <br> insérés par le firmware et
    des espaces superflus). Centralise un nettoyage sinon dupliqué
    à chaque endroit où Version/ID sont affichés.
    """

    value = info.get(key, default)

    return value.replace("<br>", "").strip()


def get_info(ip, initialize=True):

    if initialize:
        initialize_xteink()

    url = "http://%s/Read_info" % ip

    print("Xteink X3: connexion directe à", url)

    try:
        with http_opener().open(url, timeout=3) as response:
            data = response.read().decode(
                "utf-8",
                errors="replace"
            )

        print("Xteink X3: réponse =", repr(data))

    except Exception as e:
        raise XteinkError(
            "Impossible de contacter le Xteink X3 à %s\n\n%s"
            % (ip, e)
        )

    info = {
        key: value
        for key, value in INFO_PATTERN.findall(data)
    }

    info["raw"] = data

    return info


# ----------------------------------------------------------------------
# Détection du réseau local
# ----------------------------------------------------------------------

def get_local_network():

    try:
        # On demande au système quelle interface/IP il utiliserait
        # pour joindre l'extérieur.
        #
        # Aucune donnée n'est réellement envoyée avec connect()
        # sur un socket UDP.

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )

        sock.connect(
            ("8.8.8.8", 80)
        )

        local_ip = sock.getsockname()[0]

        sock.close()

        print(
            "Xteink X3: IP locale détectée :",
            local_ip
        )

        parts = local_ip.split(".")

        if len(parts) != 4:
            return None

        # Pour l'instant on suppose un LAN classique en /24.
        network = ".".join(parts[:3]) + ".0/24"

        print(
            "Xteink X3: réseau local détecté :",
            network
        )

        return network

    except Exception as e:

        print(
            "Xteink X3: impossible de déterminer "
            "le réseau local :",
            e
        )

        return None

# ----------------------------------------------------------------------
# Scan réseau
# ----------------------------------------------------------------------

def scan_network():

    network = get_local_network()

    if not network:
        raise XteinkError(
            "Impossible de déterminer le réseau local."
        )

    prefix = network.rsplit(".", 1)[0]

    ips = [
        "%s.%d" % (prefix, i)
        for i in range(1, 255)
    ]

    print(
        "Xteink X3: scan de %d adresses..." % len(ips)
    )

    found = []

    def test_ip(ip):

        try:
            info = get_info(
                ip,
                initialize=False
            )

            # Read_info répond correctement :
            # on considère donc que c'est un Xteink.
            if info.get("Version") or info.get("ID"):

                return ip, info

        except Exception:
            pass

        return None

    # L'appel bofi doit être effectué avant le scan.
    initialize_xteink()

    with ThreadPoolExecutor(max_workers=32) as executor:

        futures = [
            executor.submit(test_ip, ip)
            for ip in ips
        ]

        for future in as_completed(futures):

            try:
                result = future.result()

                if result:
                    ip, info = result

                    print(
                        "Xteink X3 trouvé :",
                        ip,
                        info
                    )

                    found.append(
                        (ip, info)
                    )

            except Exception:
                pass

    return found


# ----------------------------------------------------------------------
# Envoi EPUB
# ----------------------------------------------------------------------

# Taille des blocs envoyés un par un pendant l'upload. Un compromis
# entre fréquence de mise à jour de la progression (petit bloc =
# retour plus fluide) et overhead réseau (trop petit = beaucoup
# d'allers-retours socket pour rien).
UPLOAD_CHUNK_SIZE = 64 * 1024


def upload(ip, filename, filepath, progress_callback=None, target_folder=None):
    """
    Envoie un fichier vers le Xteink X3 en le streamant par blocs
    depuis le disque plutôt qu'en le chargeant entièrement en mémoire.

    progress_callback, si fourni, est appelé après l'envoi de chaque
    bloc avec (octets_envoyés, octets_total), ce qui permet d'afficher
    une progression réelle côté interface plutôt qu'une barre
    indéterminée.

    target_folder, si fourni, est préfixé au nom de fichier envoyé au
    firmware (ex. "Auteur/Serie/livre.epub" plutôt que "livre.epub").
    EXPÉRIMENTAL : on suppose que le firmware gère les chemins imbriqués
    dans ce champ (comportement habituel des firmwares ESP32 de type
    "éditeur SPIFFS/LittleFS", dont l'API /list, /edit ressemble
    beaucoup), mais ce n'est pas documenté ni confirmé pour ce modèle
    précis. À tester avec prudence.
    """

    boundary = "----XteinkX3%s" % uuid.uuid4().hex

    basename = os.path.basename(filename)

    if target_folder:

        remote_name = (
            target_folder.strip("/") + "/" + basename
        )

    else:

        remote_name = basename

    file_size = os.path.getsize(filepath)

    print("Xteink X3: upload filename =", repr(remote_name))
    print("Xteink X3: upload size =", file_size)

    content_type = (
        mimetypes.guess_type(basename)[0]
        or "application/octet-stream"
    )

    header = (
        (
            "--%s\r\n"
            'Content-Disposition: form-data; name="data"; filename="%s"\r\n'
            "Content-Type: %s\r\n"
            "\r\n"
        ) % (
            boundary,
            remote_name,
            content_type,
        )
    ).encode("utf-8")

    footer = (
        "\r\n--%s--\r\n" % boundary
    ).encode("utf-8")

    total_size = len(header) + file_size + len(footer)

    # Connexion HTTP brute (pas via http_opener/urllib) pour pouvoir
    # envoyer le corps de la requête bloc par bloc et progresser.
    # Comme http_opener(), ceci ne passe par aucun proxy système.
    conn = http.client.HTTPConnection(ip, timeout=60)

    try:

        conn.putrequest("POST", "/edit")

        conn.putheader(
            "Content-Type",
            "multipart/form-data; boundary=%s" % boundary,
        )

        conn.putheader(
            "Content-Length",
            str(total_size),
        )

        conn.endheaders()

        sent = 0

        conn.send(header)
        sent += len(header)

        if progress_callback:
            progress_callback(sent, total_size)

        with open(filepath, "rb") as f:

            while True:

                chunk = f.read(UPLOAD_CHUNK_SIZE)

                if not chunk:
                    break

                conn.send(chunk)
                sent += len(chunk)

                if progress_callback:
                    progress_callback(sent, total_size)

        conn.send(footer)
        sent += len(footer)

        if progress_callback:
            progress_callback(sent, total_size)

        response = conn.getresponse()

        return response.read().decode(
            "utf-8",
            errors="replace",
        )

    except Exception as e:

        raise XteinkError(
            "Erreur pendant l'envoi de %s\n\n%s"
            % (basename, e)
        )

    finally:

        conn.close()
# ----------------------------------------------------------------------
# Gestion des fichiers sur le Xteink
# ----------------------------------------------------------------------

def list_files(ip, directory="/"):
    """
    Retourne la liste des fichiers présents dans un dossier du Xteink X3.
    """

    url = "http://%s/list?dir=%s" % (
        ip,
        urllib.parse.quote(directory, safe="/"),
    )

    print(
        "Xteink X3: liste des fichiers :",
        url
    )

    # Étape 1 : la requête HTTP elle-même.
    # Un échec ici est une vraie erreur de communication
    # (réseau coupé, timeout, appareil éteint...) : elle doit
    # remonter telle quelle, sans être confondue avec le cas
    # "ce chemin n'est pas un dossier".
    try:

        with http_opener().open(
            url,
            timeout=20
        ) as response:

            data = response.read().decode(
                "utf-8",
                errors="replace"
            )

    except Exception as e:

        raise XteinkError(
            "Impossible de contacter le Xteink X3 à %s\n\n%s"
            % (ip, e)
        )

    print(
        "Xteink X3: liste reçue =",
        repr(data)
    )

    # Étape 2 : l'interprétation de la réponse.
    # Si ce n'est pas du JSON valide, on considère que le chemin
    # interrogé n'est pas un dossier (le X3 répond alors avec
    # autre chose qu'une liste). C'est un cas normal et distinct
    # d'une erreur réseau : on lève NotADirectoryError pour que
    # l'appelant puisse le traiter différemment.
    try:

        return json.loads(data)

    except ValueError as e:

        raise NotADirectoryError(
            "%s n'est pas un dossier sur le Xteink X3 "
            "(réponse non-JSON)\n\n%s"
            % (directory, e)
        )


# ----------------------------------------------------------------------
# Lecture brute d'un fichier (inspection / rétro-ingénierie)
# ----------------------------------------------------------------------

def download_file(ip, path):
    """
    Télécharge le contenu brut d'un fichier du Xteink X3.

    Le firmware stock semble servir les fichiers de son système de
    fichiers directement sur leur chemin (comme un petit serveur de
    fichiers statiques), en plus de l'API /list, /edit, /Read_info.
    Utilisé pour inspecter des fichiers internes (ex. les fichiers de
    progression de lecture repérés dans XTCache/) sans que leur format
    soit documenté au préalable.
    """

    if not path.startswith("/"):
        path = "/" + path

    quoted_path = urllib.parse.quote(
        path,
        safe="/",
    )

    url = "http://%s%s" % (
        ip,
        quoted_path,
    )

    print(
        "Xteink X3: lecture du fichier :",
        url,
    )

    try:

        with http_opener().open(
            url,
            timeout=10,
        ) as response:

            return response.read()

    except Exception as e:

        raise XteinkError(
            "Impossible de lire %s\n\n%s"
            % (
                path,
                e,
            )
        )


def verify_path_deleted(ip, directory, name):
    """
    Confirme qu'un chemin (fichier OU dossier) a bien disparu d'un
    répertoire du Xteink X3, en le relistant après une suppression.

    Même logique de précaution que verify_file_exists() côté envoi :
    rien ne garantit que le firmware ne réponde pas "OK" à une requête
    DELETE sans avoir réellement supprimé quoi que ce soit.

    Retourne True si la suppression est confirmée (absent de la
    liste), False si l'élément est toujours présent, ou None si la
    vérification elle-même a échoué (dans ce cas, on ne peut ni
    confirmer ni infirmer).
    """

    try:

        entries = list_files(
            ip,
            directory or "/",
        )

    except NotADirectoryError:

        # Le dossier parent lui-même n'est plus un dossier valide
        # (curieux, mais pas notre problème ici) : on ne peut pas
        # confirmer via cette méthode.
        return None

    except Exception:

        return None

    if not isinstance(entries, list):
        return None

    for item in entries:

        if not isinstance(item, dict):
            continue

        if item.get("name") == name:
            return False

    return True


def verify_file_exists(ip, directory, basename):
    """
    Confirme qu'un fichier existe réellement sur le Xteink X3, en
    relistant le dossier concerné après un envoi.

    Nécessaire car le firmware peut répondre "OK" en HTTP à /edit sans
    avoir réellement écrit le fichier (observé en pratique : un envoi
    vers un dossier inexistant a été confirmé par le firmware comme
    réussi côté requête, alors que ni le dossier ni le fichier
    n'avaient été créés). On ne peut donc pas se fier à la seule
    réponse HTTP de upload() pour confirmer un envoi.
    """

    try:

        entries = list_files(
            ip,
            directory or "/",
        )

    except Exception:

        # Impossible de vérifier : on ne peut pas confirmer la
        # réussite, mais on ne peut pas non plus affirmer un échec.
        return None

    if not isinstance(entries, list):
        return None

    for item in entries:

        if not isinstance(item, dict):
            continue

        if item.get("type") != "file":
            continue

        if item.get("name") == basename:
            return True

    return False


def find_duplicates(existing_files, filenames):
    """
    Compare une liste de fichiers déjà présents sur le X3 (telle que
    retournée par list_files(), une liste de dicts avec "type"/"name")
    à une liste de noms de fichiers qu'on s'apprête à envoyer.

    Retourne le sous-ensemble de `filenames` qui existe déjà (comparaison
    insensible à la casse), dans l'ordre d'origine.
    """

    existing_names = set()

    if isinstance(existing_files, list):

        for item in existing_files:

            if not isinstance(item, dict):
                continue

            if item.get("type") != "file":
                continue

            name = item.get("name", "")

            if name:
                existing_names.add(name.lower())

    return [
        filename
        for filename in filenames
        if filename.lower() in existing_names
    ]


def delete_file(ip, path):
    """
    Supprime un fichier du Xteink X3.
    """

    url = "http://%s/edit" % ip

    print(
        "Xteink X3: suppression :",
        path
    )

    data = urllib.parse.urlencode({
        "path": path,
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method="DELETE",
        headers={
            "Content-Type":
                "application/x-www-form-urlencoded",
        },
    )

    try:

        with http_opener().open(
            request,
            timeout=10
        ) as response:

            result = response.read().decode(
                "utf-8",
                errors="replace"
            )

            print(
                "Xteink X3: réponse suppression =",
                repr(result)
            )

            return result

    except Exception as e:

        raise XteinkError(
            "Erreur pendant la suppression de %s\n\n%s"
            % (
                path,
                e,
            )
        )
