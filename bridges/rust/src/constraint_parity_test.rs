use super::*;
use crate::json::parse_json;

fn check(expected: &str, actual: &str, context: &str) -> Result<(), String> {
    let expected = parse_json(expected)?;
    check_relational_leaf(
        &parse_json(context)?,
        &parse_json(actual)?,
        expected.as_object().ok_or("expected constraint")?,
        &BTreeMap::new(),
        "value",
    )
}

#[test]
fn conversion_uses_schema_or_unique_ratio() {
    let raw = r#"{"eq":2000,"min":1000,"max":3000,"in":[2000,"opaque"],"not_in":[1000],"tol":{"abs":10},"convert_from":"ms"}"#;
    let context =
        r#"{"units":{"ms->s":0.001,"ms->us":1000},"schema":{"then":{"value":{"unit":"s"}}}}"#;
    assert!(check(raw, "2", context).is_ok());
    assert!(check(raw, "2000", context).is_err());
    assert!(
        check(
            r#"{"min":1000,"convert_from":"ms"}"#,
            "2",
            r#"{"units":{"ms->s":0.001}}"#
        )
        .is_ok()
    );
    assert!(
        check(
            r#"{"min":1000,"convert_from":"ms"}"#,
            "2",
            r#"{"units":{"ms->s":0.001,"ms->us":1000}}"#
        )
        .is_err()
    );
    assert!(
        check(
            r#"{"series":{"sum_total":3000,"step_max_delta":1000},"convert_from":"ms"}"#,
            "[1,2]",
            context
        )
        .is_ok()
    );
}

#[test]
fn keys_conjoin_eq_lengths_and_membership() {
    assert!(check(r#"{"keys":{"allow":["a"],"forbid":["secret"]},"eq":{"a":1},"len":{"min":1,"max":1},"in":[{"a":1}]}"#, r#"{"a":1}"#, "{}").is_ok());
    for raw in [
        r#"{"keys":{"allow":["a"]},"eq":{"a":2}}"#,
        r#"{"allowed_keys":["a"],"min_len":2}"#,
        r#"{"allowed_keys":["a"],"not_in":[{"a":1}]}"#,
        r#"{"allowed_keys":["b"]}"#,
    ] {
        assert!(check(raw, r#"{"a":1}"#, "{}").is_err(), "{raw}");
    }
}

#[test]
fn contains_unicode_and_empty_maps() {
    for raw in [
        r#"{"contains":"😀","len":{"min":3,"max":3}}"#,
        r#"{"contains":["😀","b"]}"#,
    ] {
        assert!(check(raw, r#""a😀b""#, "{}").is_ok());
    }
    for raw in [r#"{"contains":2}"#, r#"{"contains":[1,2]}"#] {
        assert!(check(raw, "[1,2,3]", "{}").is_ok());
    }
    assert!(check(r#"{"contains":["missing"]}"#, r#""a😀b""#, "{}").is_err());
    assert!(check(r#"{"non_empty":false}"#, "{}", "{}").is_ok());
    assert!(check(r#"{"non_empty":false}"#, r#"{"a":1}"#, "{}").is_err());
    assert!(check(r#"{"non_empty":false}"#, "0", "{}").is_err());
}
