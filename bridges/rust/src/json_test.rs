use super::*;

#[test]
fn test_sha256_nist_vectors_and_crlf() {
    assert_eq!(
        sha256_hex(b""),
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    );
    assert_eq!(
        sha256_hex(b"abc"),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
    assert_eq!(
        hash_fixture_bytes(b"line1\r\nline2\r\n"),
        hash_fixture_bytes(b"line1\nline2\n")
    );
}

#[test]
fn test_json_unicode_surrogates_and_validation() {
    let v = parse_json(r#"{"crab":"\ud83e\udd80","n":-12.5e2,"arr":[true,false,null]}"#)
        .expect("valid json");
    let obj = v.as_object().expect("object");
    assert_eq!(obj.get("crab").and_then(|x| x.as_str()), Some("🦀"));
    assert_eq!(obj.get("n").and_then(|x| x.as_f64()), Some(-1250.0));
    assert!(parse_json(r#"{"x":1} trailing"#).is_err());
    assert!(parse_json(r#"{"x":01}"#).is_err());
    assert!(parse_json(r#"{"x":"\ud800"}"#).is_err());
    let deep = "[".repeat(65) + &"]".repeat(65);
    assert!(parse_json(&deep).is_err());
}

#[test]
fn test_large_numbers_serialize_as_floats_not_out_of_i64_ints() {
    for raw in ["9223372036854775808", "18446744073709551615", "1e21", "-1e21", "1.5e300"] {
        let v = parse_json(raw).expect("parse");
        let s = v.to_json_string();
        assert!(
            s.contains('e') || s.contains('E') || s.contains('.'),
            "expected float JSON literal for {}, got {}",
            raw,
            s
        );
        let rt = parse_json(&s).expect("roundtrip");
        assert_eq!(rt.as_f64(), v.as_f64());
    }
    assert_eq!(JsonValue::Number(42.0).to_json_string(), "42");
    assert_eq!(JsonValue::Number(i64::MIN as f64).to_json_string(), "-9223372036854775808");
    assert_eq!(JsonValue::Number(0.30000000000000004).to_json_string(), "0.30000000000000004");
}
