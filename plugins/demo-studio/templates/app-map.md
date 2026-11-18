# App map: <app name>

platform: <web | desktop | android | ios>
entry: <URL, installed app path, APK/IPA or build id>
login: <how to reach a signed-in state, test account notes; never store passwords here>

## Flows
| Flow | Steps (screen → action) | Selector / accessibility id | Notes |
|---|---|---|---|
| <flow> | <screen → action> | <selector> | <note or none> |

## Screens
- <screen>: <purpose, key elements>

## Sensitive elements (must be marked and blurred)
| Screen | Element | Selector | Kind (email, name, amount, token, other) |
|---|---|---|---|
| <screen> | <element> | <selector> | <kind> |

## Risks
- <popups, notifications, flaky areas, slow loads, or none>
