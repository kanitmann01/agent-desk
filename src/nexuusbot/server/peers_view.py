"""The peers page: pairing, discovery, sharing, installs.

Plain forms throughout (no script needed): generate a pairing code,
pair with another desk by address and code, refresh a paired desk's
shared plugins, install or update one. The page is honest at every
step: a desk that cannot be reached lists the cause next to its name,
update-available appears only when the publisher's version or digest
truly differs, and the trust statement below the heading says exactly
what a paired desk can and cannot do. The page rides the shared shell
(rail plus footer), so navigation belongs to the rail.
"""

import html

from nexuusbot.server import pages


def _e(value) -> str:
    """Escape any value for HTML text, turning None into an empty string.

    The peer catalog mixes missing and null fields, so every interpolation goes through
    one rule.
    """
    return html.escape(str(value if value is not None else ""))


def _pair_form(address: str = "", code: str = "") -> str:
    """The manual pairing form, optionally pre-filled with an address and code.

    Both values are escaped into their inputs and the form posts to /peers/pair.
    """
    return (
        '<form method="post" action="/peers/pair" class="cardform" '
        'data-wait="#peers-result" data-wait-shape="card" '
        'data-wait-label="Pairing with that desk..." data-busy="Pairing...">'
        f'<label for="pair-address">Desk address</label>'
        '<input id="pair-address" type="text" name="address" '
        f'placeholder="127.0.0.1:8765" value="{_e(address)}" '
        'autocomplete="off">'
        '<label for="pair-code">Its pairing code</label>'
        '<input id="pair-code" type="text" name="code" '
        f'placeholder="ABCD2345" value="{_e(code)}" autocomplete="off">'
        '<button class="btn btn-primary" type="submit">Pair</button>'
        "</form>"
    )


def _desk_section(catalog: dict) -> str:
    """This desk's identity and its live pairing code, or the block that offers to generate
    one.

    The code is displayed with its contract: it pairs a single desk and expires in ten
    minutes.
    """
    desk = catalog.get("desk") or {}
    code = catalog.get("pairingCode")
    identity = (
        f"<p>This desk is <b>{_e(desk.get('name'))}</b> "
        f"<span class='empty mono'>{_e(desk.get('peer_id'))}</span>.</p>"
    )
    if code:
        code_block = (
            f"<p class='w-big mono'>{_e(code['code'])}</p>"
            "<p class='empty'>Another desk can pair by typing this code "
            "with your address. It works once and expires in ten "
            "minutes.</p>"
        )
    else:
        code_block = (
            "<p class='empty'>No live code. Generate one; it is valid for "
            "ten minutes and pairs a single desk.</p>"
        )
    return (
        f"<h2>This desk</h2>{identity}{code_block}"
        '<form method="post" action="/peers/code" class="inlineform">'
        '<button class="btn btn-secondary" type="submit">'
        "Generate a fresh code</button></form>"
    )


def _discovered_section(catalog: dict) -> str:
    """Cards for the desks that announced themselves over the local network.

    A desk announced from this machine gets its address pre-filled into the pair form;
    one announced from elsewhere shows the address the announcement came from and gets
    an empty form, because the app only listens on its own machine.
    """
    discovered = catalog.get("discovered") or []
    if discovered:
        cards = []
        for peer in discovered:
            connectable = bool(peer.get("connectable", True))
            if connectable:
                address = (f"{peer.get('host', '127.0.0.1')}:"
                           f"{peer.get('port', '')}")
                note = (
                    f"<p class='empty mono'>{_e(address)}</p>"
                    "<p class='empty'>Discovered on this machine. Pairing "
                    "still needs its code, shown on its own peers "
                    "page.</p>"
                )
                form = _pair_form(address=address)
            else:
                # Every desk announces host 127.0.0.1 (the only address
                # its server answers on), so a desk on another machine
                # shows the address its announcement actually came from,
                # marked honestly as not connectable from here: the pair
                # form is never pre-filled with this desk's loopback.
                source = peer.get("source") or "an unknown address"
                note = (
                    f"<p class='empty mono'>{_e(source)}</p>"
                    "<div class='alert'><p>Discovered on another machine. "
                    "This app listens on its own machine only, so it "
                    "cannot be connected to from here; the address is "
                    "shown for information.</p></div>"
                )
                form = _pair_form(address="")
            cards.append(
                "<article class='card'>"
                f"<h3>{_e(peer.get('name'))}</h3>"
                + note + form
                + "</article>"
            )
        body = "".join(cards)
    else:
        body = (
            "<p class='empty'>No other desks have announced themselves "
            "yet. They appear here while they run; you can also pair by "
            "hand below.</p>"
        )
    return (
        "<h2>Discovered desks</h2>"
        "<p class='empty'>Each desk announces itself over UDP on the "
        "local network; nothing leaves it. Desks on this machine can be "
        "paired directly; desks elsewhere are listed with the address "
        "their announcement came from.</p>" + body
    )


def _plugin_row(peer_id: str, plugin: dict) -> str:
    """One plugin of a paired desk: version, whether this desk has it, and the action that
    follows.

    The form posts the peer and plugin ids to /peers/install or /peers/update; an
    installed plugin with no update gets no form.
    """
    plugin_id = _e(plugin.get("id"))
    name = _e(plugin.get("id"))
    version = _e(plugin.get("version"))
    if plugin.get("update_available"):
        state = "<span class='empty'>update available</span>"
    elif plugin.get("installed_here"):
        state = (f"installed, v{_e(plugin.get('installed_version'))} "
                 "from this peer")
    else:
        state = "not installed here"
    if plugin.get("installed_here"):
        action = (
            f"<form method='post' action='/peers/update' class='inlineform' "
            "data-wait='#peers-result' data-wait-shape='card' "
            "data-wait-label='Updating the plugin from that desk...' data-busy='Updating...'>"
            f"<input type='hidden' name='peer_id' value='{_e(peer_id)}'>"
            f"<input type='hidden' name='plugin_id' value='{plugin_id}'>"
            "<button class='btn btn-primary' type='submit'>Update</button>"
            "</form>"
        ) if plugin.get("update_available") else (
            "<p class='empty'>Up to date.</p>"
        )
    else:
        action = (
            f"<form method='post' action='/peers/install' class='inlineform' "
            "data-wait='#peers-result' data-wait-shape='card' "
            "data-wait-label='Installing the plugin from that desk...' data-busy='Installing...'>"
            f"<input type='hidden' name='peer_id' value='{_e(peer_id)}'>"
            f"<input type='hidden' name='plugin_id' value='{plugin_id}'>"
            "<button class='btn btn-primary' type='submit'>Install</button>"
            "</form>"
        )
    return (
        f"<article class='card'><h3>{name}</h3>"
        f"<p><b>v{version}</b> <span class='empty'>{state}.</span></p>"
        f"<div class='cardrow'>{action}</div></article>"
    )


def _paired_section(catalog: dict) -> str:
    """Cards for the desks already paired, each with its last refresh result and plugin
    list.

    A refresh that failed shows its cause as an alert and one that never ran says so, so
    an unknown state is never rendered as a working one.
    """
    paired = catalog.get("paired") or []
    if not paired:
        return (
            "<h2>Paired desks</h2>"
            "<p class='empty'>No desks are paired yet. Generate a code "
            "here and type it on the other desk, or take its code and "
            "its address and pair from below.</p>"
        )
    cards = []
    for peer in paired:
        state = peer.get("state") or {}
        if state.get("ok"):
            state_line = "<p class='empty'>Last refresh reached it.</p>"
        elif state.get("cause"):
            state_line = (
                "<div class='alert'><p>Unreachable: "
                + _e(state.get("cause")) + "</p></div>"
            )
        else:
            state_line = (
                "<p class='empty'>Not refreshed yet.</p>"
            )
        plugins = peer.get("plugins") or []
        if plugins:
            plugin_cards = "".join(
                _plugin_row(peer["peer_id"], plugin) for plugin in plugins)
        else:
            plugin_cards = (
                "<p class='empty'>This desk shares no plugins yet, or a "
                "refresh has not run. Refresh reads its current "
                "list.</p>")
        cards.append(
            "<article class='card'>"
            f"<h3>{_e(peer.get('name'))}</h3>"
            f"<p class='empty mono'>{_e(peer.get('base_url'))}</p>"
            f"{state_line}"
            f"<div class='cardrow'>"
            "<form method='post' action='/peers/refresh' class='inlineform' "
            "data-wait='#peers-result' data-wait-shape='card' "
            "data-wait-label='Refreshing paired desks...' data-busy='Refreshing...'>"
            "<button class='btn btn-secondary' type='submit'>Refresh</button>"
            "</form></div>"
            f"{plugin_cards}"
            "</article>"
        )
    return "<h2>Paired desks</h2>" + "".join(cards)


def render_peers_page(catalog: dict, version: str, notice: str = "",
                      inbox_count: int = 0, pair_address: str = "",
                      pair_code: str = "") -> str:
    """The whole peers page from the catalog the server assembles.

    `pair_address` and `pair_code` keep the typed words after a refused
    pairing, in the manual form that posted them.
    """
    if not catalog.get("ok"):
        notice = str(catalog.get("message", "Peers are unavailable."))
    notice_html = f"<div class='alert'><p>{_e(notice)}</p></div>" if notice else ""
    content = (
        "<h1>Peers</h1>"
        "<div id='peers-result'></div>"
        "<p>Share plugins between desks with nothing centralized. A "
        "paired desk can read only the plugins you mark shared, over "
        "plain HTTP on this network, after entering a pairing code; "
        "every install still runs the same validator a registry "
        "install runs. The server listens on this machine only, so a "
        "desk elsewhere on the LAN can be discovered but not connected "
        "to.</p>"
        f"{notice_html}"
        + _desk_section(catalog)
        + _discovered_section(catalog)
        + _paired_section(catalog)
        + "<h2>Pair by hand</h2>"
        "<p class='empty'>Type the other desk's address and pairing "
        "code yourself; discovery is a convenience, not a "
        "requirement.</p>"
        + _pair_form(address=pair_address, code=pair_code)
    )
    return pages.page_shell("Peers", "/peers", content, version,
                            inbox_count=inbox_count)
