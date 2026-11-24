# Pass 1: analysis (`analysis.json`)

Record what the rewrite must preserve before changing anything. The task lists the original's
`sentences` with ids (from `pe`'s own splitter); refer to sentences only by those ids.

```json
{
  "facts": [{"id": "f1", "fact": "The team had 42 members in 2024", "anchors": ["42", "2024"]}],
  "constraints": {"keep": ["Project Atlas"], "length_ratio": null},
  "discourse": [{"from": 2, "to": 1, "type": "cause"}],
  "register": "neutral"
}
```

| Field | Required | Rules |
|-------|----------|-------|
| `facts` | yes | The key-fact list of [key facts](facts.md): short claims, literal anchors, at most 12. |
| `constraints.keep` | no | Terms the user asked to keep verbatim; each must occur in the original. Later gates protect them. |
| `constraints.length_ratio` | no | The user's explicit length target (e.g. `0.7` for "30% shorter"), in (0, 3]. Enforced at the last gate. Leave `null` when the user gave none. |
| `discourse` | no | Relations the rewrite must keep, `{from, to, type}` with sentence ids; `type` is `cause`, `contrast`, `condition`, or `sequence`. `from` and `to` differ. |
| `register` | no | Tone of the original: `formal`, `neutral`, `casual`, `academic`, `technical`, or `literary`. |

Gate 1 fails on: invented anchors, too many or too long facts, `keep` terms that are not in the
original, an out-of-range `length_ratio`, unknown sentence ids or relation types, an unknown
register, and unknown keys. After gate 1 the file is frozen (see [harness](harness.md)).

Only record relations that the wording carries (because, but, if, then, therefore). Do not
invent structure the text does not state.

## Examples

**en**: "The bridge closed in May. Because of that, traffic doubled on Route 9."

```json
{"facts": [{"id": "f1", "fact": "Traffic doubled on Route 9 after the bridge closed", "anchors": ["Route 9"]}],
 "discourse": [{"from": 1, "to": 2, "type": "cause"}], "register": "neutral"}
```

**vi**: "Nếu trời mưa, buổi hòa nhạc sẽ dời sang thứ Bảy. Vé đã bán vẫn có hiệu lực."

```json
{"facts": [{"id": "f1", "fact": "Buổi hòa nhạc dời sang thứ Bảy nếu trời mưa", "anchors": ["thứ Bảy"]},
           {"id": "f2", "fact": "Vé đã bán vẫn có hiệu lực", "anchors": []}],
 "discourse": [], "register": "neutral"}
```

The condition sits inside sentence 1, so there is no cross-sentence relation to record.

**ja**: 「売上は20%増えた。しかし、利益は減少した。」

```json
{"facts": [{"id": "f1", "fact": "売上は20%増えたが利益は減少した", "anchors": ["20%"]}],
 "discourse": [{"from": 1, "to": 2, "type": "contrast"}], "register": "formal"}
```
