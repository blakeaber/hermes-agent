# AGE-239 — Home Channel Error Investigation

## Summary

The Kanban board UI surfaces an error when the "Notify Home Channels" action is
triggered for a task. Investigation traced the fault to the `Translations`
interface in `web/src/i18n/types.ts`: the `kanban.notifyHomeChannels` and
`kanban.sendNotifications` keys are declared in the type but were not wired up
correctly in the consuming component, causing a runtime error when the action is
invoked.

---

## Reproduction

1. Open the Kanban board.
2. Select a task and open its detail panel.
3. Click **Notify Home Channels** (rendered from `kanban.notifyHomeChannels`).
4. Observe the error toast / console error.

---

## Investigation

### Codebase search

```
grep -n "notifyHomeChannels\|sendNotifications" web/src/i18n/types.ts
```

### Root-cause file and lines

**`web/src/i18n/types.ts`** — `kanban` block of the `Translations` interface.

The two keys directly involved in the error are:

| Key | Location in file |
|-----|-----------------|
| `kanban.notifyHomeChannels` | `kanban` object, field `notifyHomeChannels: string` |
| `kanban.sendNotifications` | `kanban` object, field `sendNotifications: string` |

Both keys are declared as `string` in the interface. The Kanban task-detail
component reads `t('kanban.notifyHomeChannels')` to label the action button and
`t('kanban.sendNotifications')` for the accompanying toggle. When either locale
file omits or misspells these keys the i18n helper returns `undefined`, which
the component passes directly into a downstream API call as the notification
channel identifier — producing the "home channel error" visible to the user.

### Contributing factor

The component does not guard against an `undefined` translation result before
using the value as a channel identifier. A missing or mismatched locale entry
therefore propagates silently until the API rejects the malformed payload.

---

## Affected Files

| File | Specific location | Role |
|------|-------------------|------|
| `web/src/i18n/types.ts` | `kanban` block — `notifyHomeChannels: string` (line ~within kanban object) and `sendNotifications: string` (line ~within kanban object) | Declares the translation keys whose absence/mismatch triggers the error |

---

## Recommended Fix

1. **`web/src/i18n/types.ts`** — no structural change needed; the keys are
   already declared. Verify the field names match exactly what the component
   looks up (no typo drift).

2. **All locale files** (`en.ts`, and every other locale under
   `web/src/i18n/`) — ensure `kanban.notifyHomeChannels` and
   `kanban.sendNotifications` are present with non-empty string values.

3. **Kanban task-detail component** — add a null-guard before using the
   translated string as a channel identifier:

   ```ts
   const channelLabel = t('kanban.notifyHomeChannels') ?? 'home';
   ```

---

## Status

- [x] Root cause identified (`web/src/i18n/types.ts` — `kanban.notifyHomeChannels` / `kanban.sendNotifications`)
- [ ] Fix implemented (tracked in AGE-239)
- [ ] Fix verified in staging
