"""Owner-only offline view for the separately encrypted condition A/B shadow.

Never loads JS/CSS from third parties. NEVER publish plaintext in public Git.
Only authenticated RSA/AES and SHA-bound owner-private originals are shown.
"""
from __future__ import annotations

from hashlib import sha256
from html import escape
from pathlib import Path
import argparse
import base64
import json
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from race_ai import keirin_form_fall_shadow as shadow
from race_ai import keirin_nationwide_auto_generator as core
from race_ai import keirin_nationwide_auto_storage as store
from scripts import keirin_official_owner_view as private_file

MAX_CIPHER_BYTES = 2_000_000
MAX_PLAIN_BYTES = 2_000_000


class PrivateFormViewError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise PrivateFormViewError(reason)


def decrypt_owner_shadow(cipher, owner_private_pem):
    require(type(cipher) is bytes and 0 < len(cipher) <= MAX_CIPHER_BYTES and
            type(owner_private_pem) is bytes and 0 < len(owner_private_pem) <= 20_000,
            "FORM_OWNER_INPUT_SIZE_INVALID")
    try:
        envelope = json.loads(cipher)
        require(type(envelope) is dict and
                envelope.get("schema") == shadow.SEALED_SCHEMA,
                "FORM_OWNER_CIPHER_SCHEMA_INVALID")
        key = serialization.load_pem_private_key(
            owner_private_pem, password=None)
        require(isinstance(key, rsa.RSAPrivateKey) and key.key_size >= 3072,
                "FORM_OWNER_RSA_KEY_INVALID")
        public = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        store.checked_public_key(public)
        require(envelope["owner_spki_sha256"] ==
                store.PINNED_OWNER_SPKI_SHA256,
                "FORM_OWNER_SPKI_MISMATCH")
        nonce = base64.b64decode(envelope["nonce_b64"], validate=True)
        cipher_bytes = base64.b64decode(envelope["ciphertext_b64"],validate=True)
        wrapped = base64.b64decode(envelope["rsa_wrapped_aes_key_b64"],validate=True)
        require(len(nonce) == 12 and len(wrapped) >= 384 and
                sha256(cipher_bytes).hexdigest() == envelope["ciphertext_sha256"],
                "FORM_OWNER_CIPHER_SHA_OR_NONCE_INVALID")
        expected_aad = (
            "RACE_AI_FORM_FALL_V1|" + envelope["race_id"] + "|" +
            envelope["original_baseline_sha256"]).encode("ascii")
        require(envelope["aad_ascii"].encode("ascii") == expected_aad,
                "FORM_OWNER_AAD_MISMATCH")
        aes = key.decrypt(wrapped, padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(), label=None))
        zipped = AESGCM(aes).decrypt(nonce, cipher_bytes, expected_aad)
        unzip = zlib.decompressobj()
        plain = unzip.decompress(zipped, MAX_PLAIN_BYTES+1)
        require(len(plain) <= MAX_PLAIN_BYTES and unzip.eof and
                not unzip.unconsumed_tail and not unzip.unused_data,
                "FORM_OWNER_ZLIB_BOUNDS_INVALID")
        require(sha256(plain).hexdigest() ==
                envelope["private_shadow_plaintext_sha256"],
                "FORM_OWNER_PLAIN_SHA_MISMATCH")
        value = json.loads(plain)
        supplement, pred = value["supplement"], value["shadow"]
        require(pred["schema"] == shadow.SCHEMA and
                pred["race_id"] == envelope["race_id"] and
                pred["baseline_prediction_sha256"] ==
                    envelope["original_baseline_sha256"] and
                pred["sha256"] == core.digest({
                    k:v for k,v in pred.items() if k != "sha256"}) and
                pred["condition_supplement_sha256"] ==
                    core.digest(supplement) and
                pred["generated_at"] == envelope["generated_at"],
                "FORM_OWNER_SHADOW_SOURCE_SHA_MISMATCH")
        require(core.when(envelope["generated_at"]) <=
                core.when(envelope["sealed_at"]) and
                (core.when(envelope["cutoff_at"]) -
                 core.when(envelope["sealed_at"])).total_seconds() >= 65,
                "FORM_OWNER_CUTOFF_INVALID")
    except PrivateFormViewError:
        raise
    except (ValueError,TypeError,KeyError,UnicodeError,OverflowError, zlib.error):
        raise PrivateFormViewError("FORM_OWNER_DECRYPT_OR_DATA_INVALID") from None
    return pred, supplement


LABELS = {"IMPROVING":"上向き傾向", "DECLINING":"下降傾向",
          "NO_CLEAR_CHANGE":"明確な変化なし",
          "INSUFFICIENT_DATA":"情報不足"}


def _ticket_panel(title, baseline, conditioned):
    def numbers(rows):
        require(type(rows) is list and len(rows) <= 12,
                "FORM_OWNER_TICKETS_INVALID")
        for t in rows:
            require(type(t) is list and len(t) == 3 and
                    len(set(t)) == 3 and
                    all(type(n) is int and 1 <= n <= 9 for n in t),
                    "FORM_OWNER_TICKET_INVALID")
        return "".join('<li>' + "-".join(map(str, t)) + '</li>' for t in rows)
    return (
        '<section class="model"><h2>' + escape(title) + '</h2>'
        '<div class="compare"><div><h3>元の予想</h3><p>' + str(len(baseline)) +
        '点</p><ol>' + numbers(baseline) + '</ol></div>'
        '<div><h3>調子補正の研究候補</h3><p>' + str(len(conditioned)) +
        '点</p><ol>' + numbers(conditioned) + '</ol></div></div></section>')


def render_html(prediction, supplement):
    rows = {x["car"]:x for x in supplement["condition_evidence"]["riders"]}
    results = []
    for r in prediction["rider_assessments"]:
        car = r["car"]
        comment_entries = rows.get(car, {}).get("comments", [])
        comments = "".join(
            '<li>' + escape(c["speaker"]) + '：' + escape(c["text"]) +
            ' <span>資料SHA ' + escape(c["source_sha256"][:12]) + '…</span></li>'
            for c in comment_entries)
        context = ('落車記録あり、前後成績差：' +
                   (str(r["post_fall_change"]) if r["post_fall_change"] is not None
                    else '比較不可（不足）') if r["fall_on_record"] else
                   '直近180日内の落車記録は入力なし')
        absence = (str(r["documented_absence_days"])+'日（確認できた明示期間）'
                   if r["documented_absence_days"] is not None
                   else '期間未確認')
        results.append('<article class="rider"><h3>' + str(car) + '番車</h3>'
                       '<p>最近の成績変化：<strong>' +
                       LABELS.get(r["trend"], '判定不能') + '</strong></p>'
                       '<p>' + escape(context) + '</p>'
                       '<p>欠場の記載：' + escape(absence) + '</p>'
                       '<p>調整の研究係数：' + str(r["score_adjustment"]) + '</p>'
                       '<details><summary>本人・取材コメント（' +
                       str(r["comments_count"]) + '件）</summary><ul>' +
                       (comments or '<li>記録なし</li>') +
                       '</ul></details></article>')
    style = """
:root{color-scheme:light;font-family:system-ui,'Noto Sans JP',sans-serif;color:#242c29}
*{box-sizing:border-box}body{margin:0;background:#f7f6f1}main{max-width:1060px;margin:auto;padding:20px}
h1{font-size:clamp(25px,5vw,36px)}h2{font-size:20px}h3{font-size:15px}
p{line-height:1.7}small,.note{color:#5e6c65}
section,.rider{background:#fff;border:1px solid #e2e3df;border-radius:13px;padding:18px;margin:16px 0}
.compare{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.compare>div{background:#fcfcfa;border-radius:10px;padding:12px}
ol{list-style:none;padding:0;display:grid;grid-template-columns:repeat(2,1fr);gap:7px}
ol li{padding:10px;border:1px solid #dde1dd;border-radius:7px;font-weight:700}
.riders{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.rider{margin:0}.rider p{margin:6px 0;font-size:13px}
details{font-size:12px;margin-top:10px}li span{color:#738078}
@media(max-width:650px){main{padding:14px}.compare,.riders{grid-template-columns:1fr}
section{padding:14px}}
"""
    return ('<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\';'
            'style-src \'unsafe-inline\';script-src \'none\'">'
            '<title>事前の調子・落車考慮予想</title><style>'+style+'</style></head><body><main>'
            '<h1>調子・落車・復帰を考慮した予想</h1>'
            '<p class="note">対象レース：'+escape(prediction["race_id"])+
            '。以下は研究候補で、元の正式A/BやCとは別です。'
            '予測精度は未検証、落車だけでケガや復調を推定していません。</p>'
            + _ticket_panel("A｜基準方式",prediction["A_research"]["baseline_ranked_tickets"],
                            prediction["A_research"]["ranked_tickets"])
            + _ticket_panel("B｜6局面方式",prediction["B_research"]["baseline_ranked_tickets"],
                            prediction["B_research"]["ranked_tickets"])
            + '<h2>選手ごとの判断と根拠</h2><div class="riders">' +
            "".join(results) + '</div><p class="note">基準予想SHA：' +
            escape(prediction["baseline_prediction_sha256"]) +
            '。直近3走／前3走と落車前後成績は未校正研究指標。'
            'コメント文の健康状態は機械推定していません。'
            'データ不足の選手には減点を付けません。</p></main></body></html>')


def render_file(*, cipher_path, private_pem_path, out_path):
    out = private_file._destination(out_path)
    cipher = private_file._read_input(cipher_path, MAX_CIPHER_BYTES)
    key = private_file._read_input(private_pem_path, 20_000, private_key=True)
    pred, supplement = decrypt_owner_shadow(cipher, key)
    html = render_html(pred, supplement).encode("utf-8")
    require(len(html) <= 2_000_000, "FORM_OWNER_HTML_TOO_LARGE")
    private_file._write_new_private(out, html)
    return {"status": "FORM_CONDITIONED_PRIVATE_VIEW_CREATED",
            "race_id": pred["race_id"],
            "A_points": len(pred["A_research"]["ranked_tickets"]),
            "B_points": len(pred["B_research"]["ranked_tickets"])}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--cipher", required=True)
    p.add_argument("--owner-private-pem", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    try:
        info = render_file(cipher_path=a.cipher,
                           private_pem_path=a.owner_private_pem, out_path=a.out)
        print(json.dumps(info, sort_keys=True))
        return 0
    except (PrivateFormViewError, OSError, ValueError, TypeError):
        print('{"status":"HOLD_FORM_CONDITION_OWNER_VIEW"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
