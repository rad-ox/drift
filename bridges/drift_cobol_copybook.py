"""Zero-dependency COBOL 85 copybook PIC parser and fixed-width record marshaler."""
from __future__ import annotations

from typing import Any


def _to_snake(name: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(name):
        if "A" <= ch <= "Z":
            if i > 0 and out and out[-1] != "_" and not ("A" <= name[i - 1] <= "Z"):
                out.append("_")
            out.append(ch.lower())
        elif ch.isalnum():
            out.append(ch.lower())
        elif ch in "-./:" and out and out[-1] != "_":
            out.append("_")
    res = "".join(out).strip("_") or "field"
    return f"f_{res}" if res[0].isdigit() else res


def _parse_pic_spec(raw_pic: str) -> dict[str, Any]:
    spec = raw_pic.rstrip(".;").upper()
    signed = spec.startswith("S")
    if signed:
        spec = spec[1:]
    int_d, dec_d, alpha_l, after_v, i = 0, 0, 0, False, 0
    while i < len(spec):
        ch = spec[i]
        if ch in ("V", "."):
            after_v, i = True, i + 1
            continue
        cnt = 1
        if i + 1 < len(spec) and spec[i + 1] == "(":
            end = spec.find(")", i + 2)
            if end > i + 2 and spec[i + 2 : end].isdigit():
                cnt, i = int(spec[i + 2 : end]), end + 1
            else:
                i += 1
        else:
            i += 1
        if ch in ("X", "A", "N"):
            alpha_l += cnt
        elif ch in ("9", "Z"):
            if after_v:
                dec_d += cnt
            else:
                int_d += cnt
    if int_d > 0 or dec_d > 0:
        return {
            "kind": "decimal" if dec_d > 0 else "int",
            "byte_len": int_d + dec_d + (1 if signed else 0),
            "digits": int_d,
            "scale": dec_d,
            "signed": signed,
        }
    return {"kind": "alpha", "byte_len": max(alpha_l, 1), "digits": 0, "scale": 0, "signed": False}


def parse_copybook_layout(copybook_text: str) -> list[dict[str, Any]]:
    layout: list[dict[str, Any]] = []
    offset = 0
    for raw_line in copybook_text.splitlines():
        line = raw_line.rstrip()
        if len(line) >= 7 and all(c.isdigit() or c == " " for c in line[:6]):
            if line[6] in ("*", "/", "D", "d"):
                continue
            line = line[7:72]
        if "*>" in line:
            line = line.split("*>", 1)[0]
        trimmed = line.strip().rstrip(".")
        if not trimmed or trimmed.startswith("*"):
            continue
        parts = trimmed.split()
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        lvl, name = int(parts[0]), parts[1]
        up_parts = [p.upper() for p in parts]
        if lvl in (1, 66, 77, 88) and "PIC" not in up_parts and "PICTURE" not in up_parts:
            continue
        pic_raw = ""
        for idx in range(2, len(parts) - 1):
            if up_parts[idx] in ("PIC", "PICTURE"):
                pic_raw = parts[idx + 2] if up_parts[idx + 1] == "IS" and idx + 2 < len(parts) else parts[idx + 1]
                break
        if not pic_raw:
            continue
        occurs = 1
        for idx in range(2, len(parts) - 1):
            if up_parts[idx] == "OCCURS" and parts[idx + 1].isdigit():
                occurs = int(parts[idx + 1])
                break
        info = _parse_pic_spec(pic_raw)
        if name.upper() != "FILLER":
            layout.append({
                "name": name,
                "key": _to_snake(name),
                "offset": offset,
                "byte_len": info["byte_len"],
                "occurs": occurs,
                "kind": info["kind"],
                "digits": info["digits"],
                "scale": info["scale"],
                "signed": info["signed"],
            })
        offset += info["byte_len"] * occurs
    return layout


def _fmt_num_field(mag: int, blen: int, signed: bool, neg: bool) -> str:
    if signed:
        width = blen - 1
        return ("-" if neg else "+") + str(mag).zfill(width)[-width:]
    return str(mag).zfill(blen)[-blen:]


def marshal_record(layout: list[dict[str, Any]], values: dict[str, Any]) -> str:
    chunks: list[str] = []
    offset = 0
    for fld in layout:
        chunks.append(" " * max(0, fld["offset"] - offset))
        raw_val = values.get(fld["key"], values.get(fld["name"]))
        blen, kind, signed = fld["byte_len"], fld["kind"], fld["signed"]
        offset = fld["offset"] + blen
        if kind == "alpha":
            chunks.append(("" if raw_val is None else str(raw_val))[:blen].ljust(blen, " "))
        elif kind == "int":
            iv = 0 if raw_val is None else int(raw_val)
            chunks.append(_fmt_num_field(abs(iv) if signed else max(0, iv), blen, signed, iv < 0))
        else:
            fv = 0.0 if raw_val is None else float(raw_val)
            scaled = int(round(abs(fv) * (10 ** fld["scale"])))
            chunks.append(_fmt_num_field(scaled, blen, signed, fv < 0))
    return "".join(chunks)


def unmarshal_record(layout: list[dict[str, Any]], raw_record: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for fld in layout:
        off, blen, kind = fld["offset"], fld["byte_len"], fld["kind"]
        seg = raw_record[off : off + blen].ljust(blen, " ")
        if kind == "alpha":
            out[fld["key"]] = seg.rstrip(" ")
        elif kind == "int":
            out[fld["key"]] = int(seg.strip() or "0")
        else:
            signed, scale = fld["signed"], fld["scale"]
            sign = (-1 if seg[0] == "-" else 1) if signed else 1
            digits = (seg[1:] if signed else seg).strip() or "0"
            out[fld["key"]] = round(sign * (int(digits) / (10 ** scale)), scale)
    return out
