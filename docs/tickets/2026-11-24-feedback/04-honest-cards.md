# 04: Honest cards

**What to build:** the home screen and Desk health list only what this desk can actually run. A plugin that contributes no widget has no tile and no health row. A plugin whose source needs the network says so in reader language, offers Remove as its only action, stays off the home screen, and is named in the marketplace before install and on the Installed page. Desk health shows the three desk sources with a counter that counts those rows, then the plugins that feed a tile as a second labelled group with its own count. A plugin that never ran says "never". Unknown plugin kinds stop wearing the DIGEST tag. The digest survives a malformed event date.

**Blocked by:** 01.

**Status:** queued.

- [ ] A widget-less plugin (the shipped presentation-starter) has no home-screen tile and no Desk health row, and its setup card stays wherever setup is shown.
- [ ] A network-only plugin (the shipped competitor-watch) has no home-screen tile.
- [ ] Where that plugin is reached (Plugins, detail, Installed), it says "This desk cannot read web pages yet" and offers Remove as its only action; there is no Re-test.
- [ ] The marketplace says before install, on the card, the detail page and the consent sheet, that the plugin cannot run on this desk.
- [ ] The Installed page repeats the state and offers Remove.
- [ ] Desk health shows the three desk sources with a counter that counts exactly those rows, and the plugins that feed a tile as a second labelled group with its own count.
- [ ] A plugin that never ran shows "never", not the current time.
- [ ] "Re-test now" appears only where a re-test can change the reading; it is absent from a no-widget plugin and a network-only plugin.
- [ ] An unknown plugin kind no longer defaults to DIGEST, each kind carries one word, and two different cells no longer carry the same tag for different reasons.
- [ ] A malformed calendar event start does not throw: the digest card still renders, and the item keeps its title and detail.
- [ ] The Page watch placeholder no longer offers "Add a page" while this desk cannot read web pages; it keeps its wireframe and names the limit.
- [ ] The filter that removes the two kinds of card runs once where both dashboard surfaces get their cards, so the SPA payload and the server page agree.
- [ ] Component and server tests cover the filtered cards, the two health groups, the two counters, the word "never" and the marketplace notice.
- [ ] `python tools/ci_local.py` passes 7/7.
