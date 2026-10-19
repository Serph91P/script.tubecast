# Per-phone YouTube profiles

Use this with the profile-aware
[YouTube fork](https://github.com/Serph91P/plugin.video.youtube), not an
unmodified upstream YouTube add-on.

1. Install matching builds of both forks and sign in to the required profiles
   inside the YouTube add-on. Enable remote watch history there if desired.
2. Enable **Use a separate YouTube profile for each phone** in TubeCast.
   Use the YouTube playback backend; Tubed is not part of this integration.
3. Cast from one phone. On the first playback, Kodi asks which existing
   signed-in YouTube profile belongs to it. Repeat with the next phone.
4. Reconnect/next/previous/resume/queue advance all retain the sender identity.
   Only one phone may be connected at once. Each phone must always use one
   account. Names and avatars are not used to guess accounts.

The YouTube add-on stores the pairing and owns tokens and history. TubeCast
passes only a SHA-256 hash of the Lounge sender device ID and an optional
name. This is profile routing on the existing local Cast trust boundary, not
an authorization mechanism. An app reinstall or changed sender ID may prompt
again. To reassign a phone, use the YouTube settings action **Reset TubeCast
phone associations** (resets all associations, not sign-ins).

The setting is off by default, preserving legacy playback. When enabled,
missing/ambiguous sender identity or a missing/incompatible companion package
blocks playback rather than writing to Kodi's currently selected account.
Selecting a profile and then cancelling does not start playback. The YouTube
add-on also fails closed if its pairing is invalid or cannot be saved.

The setting has no effect on Tubed. `playback-addon=0` is the YouTube code path,
`playback-addon=1` is Tubed. The backend spinner captions now match those values.

## Acceptance before release

The pytest suite uses explicit Kodi/network/player mocks. A native check is
still required: use two phones with different signed-in accounts, keep Kodi's
globally displayed YouTube profile different, then play/stop/next/reconnect
from each phone separately and check both real account histories. Also check
cancelled pairing, a signed-out/deleted profile, reset, and the incompatible
YouTube add-on error.
