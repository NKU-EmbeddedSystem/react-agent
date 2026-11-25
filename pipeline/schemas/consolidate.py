"""Independent strict output contracts for the opt-in review/consolidation flow."""


def obj(**props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def array(items):
    return {"type": "array", "items": items}


TEXT = {"type": "string"}
STRINGS = array(TEXT)
EVIDENCE = obj(id=TEXT, doc={"type": "string", "enum": ["main", "si"]},
               page={"type": "integer"}, bbox={"type": ["array", "null"], "items": {"type": "number"}},
               quote=TEXT)
FINDING_CODES = ("yield_unspecified", "conditions_unspecified", "reference_unresolved", "variables_missing",
                 "evidence_conflict", "condition_applicability", "other_review")
FINDING = obj(code={"type": "string", "enum": list(FINDING_CODES)}, field=TEXT, message=TEXT,
              status={"type": "string", "enum": ["open", "resolved"]}, evidence_ids=STRINGS)
PATCH = obj(path=TEXT, value_json=TEXT, reason=TEXT, evidence_ids=STRINGS)
DEFINITION = obj(field=TEXT, label=TEXT, text=TEXT, evidence_ids=STRINGS)
MEASUREMENT = obj(kind={"type": "string", "enum": ["nmr_integral", "other"]}, field=TEXT,
                  text=TEXT, evidence_ids=STRINGS)
REVIEW = obj(records=array(obj(record_id=TEXT, findings=array(FINDING), patches=array(PATCH),
                               definitions=array(DEFINITION), measurements=array(MEASUREMENT),
                               evidence=array(EVIDENCE),
                               category={"type": "string", "enum": ["core", "auxiliary", "undetermined"]})))
SUMMARY = obj(relations=array(obj(left=TEXT, right=TEXT,
                                  relation={"type": "string", "enum": ["same_experiment", "candidate", "distinct"]},
                                  reason=TEXT, evidence_ids=STRINGS)))
