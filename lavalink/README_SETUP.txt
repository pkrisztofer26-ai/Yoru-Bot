YORU MUSIC 2.0 — LAVALINK + LAVASRC SETUP
==========================================

A Yoru v3.17.1 a Lavalink v4 node-ot használja elsődleges zenei backendként.
A Python bot Wavelinkkel csatlakozik hozzá. A Spotify linket Yoru közvetlenül
átadja Lavalinknek, a LavaSrc feloldja a Spotify metadata-t és egy konfigurált
mirror providerből kér lejátszható audio tracket.

AJÁNLOTT RELEASE STACK
- Lavalink 4.2.2
- LavaSrc 4.8.3
- youtube-source 1.18.1
- Wavelink 3.5.2 (a bot requirements.txt része)

FONTOS
A Lavalink külön Java process/service. A Yoru ZIP szándékosan NEM tartalmaz
Java runtime-ot, Lavalink.jar-t vagy secretet. PebbleHost Python instance esetén
futtasd a Lavalinket olyan külön instance-on/node-on, amely Java process futtatását
engedi, majd a Yoru .env-ben add meg annak URI-ját és passwordjét.

LÉPÉSEK
1. Szerezz be Lavalink 4.2.2-t a hivatalos Lavalink release-ből.
2. Másold ezt: lavalink/application.yml.example -> application.yml
3. A Lavalink környezetében állítsd be:
   LAVALINK_PASSWORD=<erős saját jelszó>
   SPOTIFY_CLIENT_ID=<Spotify developer app client id>
   SPOTIFY_CLIENT_SECRET=<Spotify developer app client secret>
4. Indítsd a Lavalink node-ot az application.yml mellett.
5. A Yoru saját .env fájljában állítsd be:
   LAVALINK_URI=http://HOST:2333
   LAVALINK_PASSWORD=<ugyanaz a jelszó>
   LAVALINK_IDENTIFIER=yoru-main
6. Indítsd újra Yorut, majd /settings -> Music alatt ellenőrizd a Lavalink státuszt.
   A "Lavalink reconnect" gombbal újrapróbálható a kapcsolat.

FALLBACK
Ha a node nincs konfigurálva vagy átmenetileg offline, Yoru nem áll le: a meglévő
spotDL + yt-dlp + FFmpeg legacy backend marad fallbackként.

BIZTONSÁG
- application.yml-ben ne commitolj valódi Spotify secretet vagy Lavalink passwordöt.
- A secretet környezeti változóban tárold.
- /settings nem írja ki a Lavalink jelszót vagy a Spotify secretet.
