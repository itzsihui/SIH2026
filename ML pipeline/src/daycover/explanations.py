"""Phase 15: read-only, template-grounded explanations over a Phase 9 ``daycover.part2.v1`` snapshot.

* Input is an already-authorised snapshot dict; this module has no ledger/provider access and cannot mutate anything.
* Only whitelisted enum/number fields are rendered. Free-text fields in the snapshot (reviewer notes, source refs) are never
  echoed, so injected text cannot reach a customer.
* ``check_text`` verifies any rendered or model-polished text against the facts (numbers, dates, claim ids, forbidden claims).
* Non-English templates are drafts needing native-speaker review; they carry ``translation_status``.
"""
from __future__ import annotations

import re

SCHEMA = "daycover.explanation.v1"
LANGS = ("en", "zh", "ms", "ta")
TRANSLATION_STATUS = {"en": "authored", "zh": "draft_needs_native_review", "ms": "draft_needs_native_review",
                      "ta": "draft_needs_native_review"}

# state ids per peril
STATES = ("entitlement_recorded", "entitlement_under_review", "capped", "closure_excluded", "pending_evidence",
          "not_triggered", "not_evaluated", "term_inactive", "unclear")


def _cents(v) -> int:
    return int(round(float(v) * 100)) if v is not None else 0


def money(c: int) -> str:
    return f"S${c // 100}.{c % 100:02d}"


def _peril_state(d: dict) -> str:
    s, e = d.get("status"), d.get("effect")
    if s == "TRIGGERED":
        return "entitlement_recorded" if e == "accepted" else "entitlement_under_review" if e == "review_pending" else "unclear"
    return {"CAPPED": "capped", "SUPPRESSED": "closure_excluded", "PENDING": "pending_evidence", "NO_TRIGGER": "not_triggered",
            "NOT_EVALUATED": "not_evaluated", "INACTIVE": "term_inactive"}.get(s, "unclear")


def facts(snap: dict) -> dict:
    """Extract the only values an explanation may state. Identity/personal fields are deliberately excluded."""
    if snap.get("schema_version") != "daycover.part2.v1":
        raise ValueError("unsupported snapshot schema")
    rem, pol = snap["coverage"]["remaining"], snap["policy"]
    perils = {}
    for d in snap["decisions"]:
        st = _peril_state(d)
        perils[d["peril"]] = {"state": st, "amount_cents": _cents(d.get("target_entitlement_sgd")) if st.startswith("entitlement") else 0,
                              "context_stale": d.get("current_context_matches") is False and d.get("status") != "NOT_EVALUATED"}
    st, bill = snap["settlement"], snap["billing"]
    summ = st["summary"]
    insts = st.get("instructions", [])
    uncertain = any(i.get("status") == "uncertain" for i in insts)
    pay = ("mock_confirmed" if summ["confirmed_mock_cents"] > 0 else "mock_pending" if summ["reserved_cents"] > 0
           else "not_submitted" if summ["net_entitlement_cents"] > 0 else "none")
    bs = bill["summary"]
    return {"as_of_day": snap["as_of_day"], "contract_version": pol["accepted_version"], "contract_sha256": pol["contract_sha256"],
            "term_start": str(pol["start"]), "term_end": str(pol["end"]),
            "remaining": {"rain_events": rem["rain_events"], "haze_days": rem["haze_days"], "rain_cents": rem["rain_cents"],
                          "haze_cents": rem["haze_cents"], "combined_cents": rem["combined_cents"]},
            "perils": perils,
            "payment": {"state": pay, "uncertain": uncertain, "net_entitlement_cents": summ["net_entitlement_cents"],
                        "confirmed_mock_cents": summ["confirmed_mock_cents"], "reserved_cents": summ["reserved_cents"],
                        "review_required": bool(st.get("review_required"))},
            "billing": {"prepared": bool(bill["prepared"]), "annual_cents": bs["annual_obligation_cents"],
                        "due_outstanding_cents": bs["due_outstanding_cents"], "failed_attempt_cents": bs["failed_attempt_cents"],
                        "review_required": bool(bill["review_required"])},
            "rain_timing_verified": bool(snap["boundaries"]["rain_timing_verified"]),
            "mode": "simulation_only"}


T = {
 "en": {
  "header": "Simulation only. Policy {version}, checked for {day}.",
  "rain": "Rain:", "haze": "Haze:",
  "entitlement_recorded": "{p} {amt} is recorded as an entitlement under the contract rules.",
  "entitlement_under_review": "{p} an entitlement of {amt} is recorded but under review because evidence changed.",
  "capped": "{p} the policy-year limit was already reached, so nothing more is recorded.",
  "closure_excluded": "{p} your centre was closed that day, so nothing is recorded and no limit is used.",
  "pending_evidence": "{p} the weather or closure evidence is not complete yet, so this day is pending, not denied.",
  "not_triggered": "{p} the trigger was not met, so nothing is recorded.",
  "not_evaluated": "{p} this day has not been evaluated yet; viewing it does not evaluate or pay it.",
  "term_inactive": "{p} the policy term was not active on that day.",
  "unclear": "{p} the status is unclear; please contact the support team.",
  "stale": "The source data changed after this decision was made, so it needs review.",
  "remaining": "Remaining cover: rain {re} event(s) ({rc}), haze {hd} day(s) ({hc}), combined {cc}.",
  "pay_none": "No payment is due for this day.",
  "pay_not_submitted": "An entitlement of {n} exists but no payment has been submitted.",
  "pay_mock_pending": "A simulated payment of {r} is pending; this is not real money.",
  "pay_mock_confirmed": "A simulated payment of {c} was confirmed in the test wallet; no real money moved.",
  "uncertain": "A payment outcome is uncertain and is under review.",
  "bill_unprepared": "No billing schedule has been prepared; nothing was charged.",
  "bill_failed": "A simulated premium attempt of {f} failed; no real debit occurred.",
  "bill_due": "Simulated premium outstanding and due: {d}.",
  "rain_timing": "Rain timing rules are not yet verified, so rain results are provisional.",
  "closing": "This explanation cannot change or approve any payout or price."},
 "zh": {
  "header": "仅为模拟。保单 {version}，查询日期 {day}。", "rain": "降雨：", "haze": "烟霾：",
  "entitlement_recorded": "{p} 根据合约规则，已记录 {amt} 的赔付权益。",
  "entitlement_under_review": "{p} 已记录 {amt} 的权益，但因证据变更正在复核。",
  "capped": "{p} 保单年度限额已用完，不再记录。",
  "closure_excluded": "{p} 您的中心当天关闭，因此不记录赔付，也不占用限额。",
  "pending_evidence": "{p} 天气或关闭证据尚不完整，该日处于待定状态，并非被拒绝。",
  "not_triggered": "{p} 未达触发条件，因此没有记录。",
  "not_evaluated": "{p} 该日尚未评估；查看本页不会进行评估或付款。",
  "term_inactive": "{p} 当天保单期间未生效。",
  "unclear": "{p} 状态不明确，请联系支持团队。",
  "stale": "该决定作出后数据来源已变更，需要复核。",
  "remaining": "剩余保障：降雨 {re} 次（{rc}），烟霾 {hd} 天（{hc}），合计 {cc}。",
  "pay_none": "该日无需付款。",
  "pay_not_submitted": "存在 {n} 的权益，但尚未提交付款。",
  "pay_mock_pending": "{r} 的模拟付款待处理；这不是真实款项。",
  "pay_mock_confirmed": "{c} 的模拟付款已在测试钱包确认；没有真实资金转移。",
  "uncertain": "付款结果不确定，正在复核。",
  "bill_unprepared": "尚未准备账单计划；没有任何扣费。",
  "bill_failed": "{f} 的模拟保费扣款失败；没有发生真实扣款。",
  "bill_due": "模拟保费未付且已到期：{d}。",
  "rain_timing": "降雨时间规则尚未核实，因此降雨结果为暂定。",
  "closing": "本说明无法更改或批准任何赔付或价格。"},
 "ms": {
  "header": "Simulasi sahaja. Polisi {version}, disemak untuk {day}.", "rain": "Hujan:", "haze": "Jerebu:",
  "entitlement_recorded": "{p} {amt} direkodkan sebagai kelayakan di bawah peraturan kontrak.",
  "entitlement_under_review": "{p} kelayakan {amt} direkodkan tetapi dikaji semula kerana bukti berubah.",
  "capped": "{p} had tahun polisi sudah dicapai, jadi tiada rekod tambahan.",
  "closure_excluded": "{p} pusat anda ditutup pada hari itu, jadi tiada rekod dan had tidak digunakan.",
  "pending_evidence": "{p} bukti cuaca atau penutupan belum lengkap, jadi hari ini tertangguh, bukan ditolak.",
  "not_triggered": "{p} pencetus tidak dipenuhi, jadi tiada rekod.",
  "not_evaluated": "{p} hari ini belum dinilai; melihatnya tidak menilai atau membayar.",
  "term_inactive": "{p} tempoh polisi tidak aktif pada hari itu.",
  "unclear": "{p} status tidak jelas; sila hubungi pasukan sokongan.",
  "stale": "Data sumber berubah selepas keputusan ini dibuat, jadi ia perlu dikaji semula.",
  "remaining": "Perlindungan berbaki: hujan {re} kejadian ({rc}), jerebu {hd} hari ({hc}), gabungan {cc}.",
  "pay_none": "Tiada bayaran perlu dibuat untuk hari ini.",
  "pay_not_submitted": "Kelayakan {n} wujud tetapi tiada bayaran dihantar.",
  "pay_mock_pending": "Bayaran simulasi {r} sedang menunggu; ini bukan wang sebenar.",
  "pay_mock_confirmed": "Bayaran simulasi {c} disahkan dalam dompet ujian; tiada wang sebenar bergerak.",
  "uncertain": "Hasil bayaran tidak pasti dan sedang dikaji.",
  "bill_unprepared": "Tiada jadual bil disediakan; tiada apa yang dicaj.",
  "bill_failed": "Percubaan premium simulasi {f} gagal; tiada debit sebenar berlaku.",
  "bill_due": "Premium simulasi tertunggak dan sudah genap masa: {d}.",
  "rain_timing": "Peraturan masa hujan belum disahkan, jadi keputusan hujan adalah sementara.",
  "closing": "Penjelasan ini tidak boleh mengubah atau meluluskan sebarang bayaran atau harga."},
 "ta": {
  "header": "உருவகப்படுத்தல் மட்டும். பாலிசி {version}, {day} நாளுக்கான சோதனை.", "rain": "மழை:", "haze": "புகைமூட்டம்:",
  "entitlement_recorded": "{p} ஒப்பந்த விதிகளின்படி {amt} உரிமை பதிவு செய்யப்பட்டுள்ளது.",
  "entitlement_under_review": "{p} {amt} உரிமை பதிவாகியுள்ளது, ஆனால் சான்று மாறியதால் மறுஆய்வில் உள்ளது.",
  "capped": "{p} பாலிசி ஆண்டு வரம்பு ஏற்கனவே எட்டப்பட்டது, எனவே கூடுதல் பதிவு இல்லை.",
  "closure_excluded": "{p} அன்று உங்கள் மையம் மூடப்பட்டிருந்தது, எனவே பதிவு இல்லை; வரம்பும் பயன்படுத்தப்படவில்லை.",
  "pending_evidence": "{p} வானிலை அல்லது மூடல் சான்று இன்னும் முழுமையடையவில்லை; இந்த நாள் நிலுவையில் உள்ளது, நிராகரிக்கப்படவில்லை.",
  "not_triggered": "{p} தூண்டுதல் நிபந்தனை பூர்த்தியாகவில்லை, எனவே பதிவு இல்லை.",
  "not_evaluated": "{p} இந்த நாள் இன்னும் மதிப்பிடப்படவில்லை; பார்ப்பதால் மதிப்பீடோ பணம் செலுத்தலோ நடக்காது.",
  "term_inactive": "{p} அன்று பாலிசி காலம் செயலில் இல்லை.",
  "unclear": "{p} நிலை தெளிவாக இல்லை; ஆதரவு குழுவைத் தொடர்பு கொள்ளவும்.",
  "stale": "இந்த முடிவுக்குப் பின் மூலத் தரவு மாறியது, எனவே மறுஆய்வு தேவை.",
  "remaining": "மீதமுள்ள காப்பு: மழை {re} நிகழ்வு ({rc}), புகைமூட்டம் {hd} நாள் ({hc}), மொத்தம் {cc}.",
  "pay_none": "இந்த நாளுக்குப் பணம் செலுத்த வேண்டியதில்லை.",
  "pay_not_submitted": "{n} உரிமை உள்ளது, ஆனால் பணம் செலுத்தல் சமர்ப்பிக்கப்படவில்லை.",
  "pay_mock_pending": "{r} உருவகப்படுத்தப்பட்ட பணம் நிலுவையில் உள்ளது; இது உண்மையான பணம் அல்ல.",
  "pay_mock_confirmed": "{c} உருவகப்படுத்தப்பட்ட பணம் சோதனை பணப்பையில் உறுதியானது; உண்மையான பணம் நகரவில்லை.",
  "uncertain": "பணம் செலுத்தல் முடிவு உறுதியாக இல்லை; மறுஆய்வில் உள்ளது.",
  "bill_unprepared": "கட்டண அட்டவணை தயாரிக்கப்படவில்லை; எதுவும் வசூலிக்கப்படவில்லை.",
  "bill_failed": "{f} உருவகப்படுத்தப்பட்ட பிரீமியம் முயற்சி தோல்வி; உண்மையான பற்று நடக்கவில்லை.",
  "bill_due": "உருவகப்படுத்தப்பட்ட பிரீமியம் நிலுவை மற்றும் காலாவதி: {d}.",
  "rain_timing": "மழை நேர விதிகள் இன்னும் சரிபார்க்கப்படவில்லை, எனவே மழை முடிவுகள் தற்காலிகமானவை.",
  "closing": "இந்த விளக்கம் எந்த கொடுப்பனவையோ விலையையோ மாற்றவோ அங்கீகரிக்கவோ முடியாது."},
}


def render(f: dict, lang: str = "en") -> dict:
    if lang not in T:
        raise ValueError("unsupported language")
    t = T[lang]
    lines, ids = [], []

    def add(i, **kw):
        ids.append(i)
        lines.append(t[i].format(**kw) if kw or "{" in t[i] else t[i])

    add("header", version=f["contract_version"], day=f["as_of_day"])
    for peril in ("rain", "haze"):
        p = f["perils"].get(peril)
        if not p:
            continue
        ids.append(f"{peril}:{p['state']}")
        lines.append(t[p["state"]].format(p=t[peril], amt=money(p["amount_cents"])))
        if p["context_stale"]:
            add("stale")
    r = f["remaining"]
    add("remaining", re=r["rain_events"], rc=money(r["rain_cents"]), hd=r["haze_days"], hc=money(r["haze_cents"]), cc=money(r["combined_cents"]))
    pay = f["payment"]
    add({"none": "pay_none", "not_submitted": "pay_not_submitted", "mock_pending": "pay_mock_pending", "mock_confirmed": "pay_mock_confirmed"}[pay["state"]],
        n=money(pay["net_entitlement_cents"]), r=money(pay["reserved_cents"]), c=money(pay["confirmed_mock_cents"]))
    if pay["uncertain"]:
        add("uncertain")
    b = f["billing"]
    if not b["prepared"]:
        add("bill_unprepared")
    if b["failed_attempt_cents"]:
        add("bill_failed", f=money(b["failed_attempt_cents"]))
    if b["due_outstanding_cents"]:
        add("bill_due", d=money(b["due_outstanding_cents"]))
    if not f["rain_timing_verified"]:
        add("rain_timing")
    add("closing")
    return {"schema_version": SCHEMA, "language": lang, "translation_status": TRANSLATION_STATUS[lang], "claim_ids": ids,
            "text": "\n".join(lines), "grounding": {"contract_version": f["contract_version"], "contract_sha256": f["contract_sha256"],
                                                    "evidence_day": f["as_of_day"], "term": [f["term_start"], f["term_end"]]},
            "read_only": True, "decides_payouts": False, "mode": "simulation_only"}


def explain(snap: dict, lang: str = "en") -> dict:
    f = facts(snap)
    out = render(f, lang)
    chk = check_text(out["text"], f, out["claim_ids"], lang)
    if not chk["ok"]:  # never emit text that fails its own factual check
        raise AssertionError("explanation failed factual check: " + ",".join(chk["problems"]))
    return {**out, "factual_check": chk}


NUM = re.compile(r"S\$\d+(?:\.\d{2})?|\d{4}-\d{2}-\d{2}|\d+")
FORBIDDEN_EN = re.compile(r"guarantee|we (?:will|have) (?:pay|paid|approve|transfer)|has been paid to your|transferred to your bank|"
                          r"real money (?:was|has been) (?:sent|paid)|your (?:payout|premium) (?:is|has been) (?:increased|changed|approved)|"
                          r"i (?:have )?(?:approved|changed|updated|cancel)", re.I)


def expected_ids(f: dict) -> set[str]:
    return {"header", "remaining", "closing"} | {f"{p}:{v['state']}" for p, v in f["perils"].items()}


def allowed_tokens(f: dict, lang: str = "en") -> set[str]:
    r, pay, b = f["remaining"], f["payment"], f["billing"]
    toks = {f["as_of_day"], f["contract_version"], money(r["rain_cents"]), money(r["haze_cents"]), money(r["combined_cents"]),
            str(r["rain_events"]), str(r["haze_days"]), money(pay["net_entitlement_cents"]), money(pay["reserved_cents"]),
            money(pay["confirmed_mock_cents"]), money(b["failed_attempt_cents"]), money(b["due_outstanding_cents"]), money(b["annual_cents"])}
    toks |= {money(p["amount_cents"]) for p in f["perils"].values()}
    # the version string contains digits; allow its components so tokenised numbers match
    toks |= set(NUM.findall(f["contract_version"]))
    return toks


def check_text(text: str, f: dict, claim_ids: list[str] | None = None, lang: str = "en") -> dict:
    """Verify numbers/dates against facts, mandatory claim ids and forbidden promises. Free text outside en is number-checked only."""
    problems = []
    allowed = allowed_tokens(f, lang)
    for tok in NUM.findall(text):
        if tok not in allowed and not any(tok in a for a in allowed):
            problems.append(f"unsupported_number:{tok}")
    if FORBIDDEN_EN.search(text):
        problems.append("forbidden_claim")
    if claim_ids is not None:
        missing = expected_ids(f) - set(claim_ids)
        if missing:
            problems.append("missing_claims:" + ",".join(sorted(missing)))
        pay_ok = {"none": "pay_none", "not_submitted": "pay_not_submitted", "mock_pending": "pay_mock_pending", "mock_confirmed": "pay_mock_confirmed"}
        if pay_ok[f["payment"]["state"]] not in claim_ids:
            problems.append("payment_state_not_stated")
        for c in claim_ids:
            if c.endswith(":entitlement_recorded") and f["perils"][c.split(":")[0]]["state"] != "entitlement_recorded":
                problems.append("entitlement_claim_without_fact")
    else:
        problems.append("claim_ids_absent_unverifiable_semantics") if lang != "en" else None
    return {"ok": not problems, "problems": problems, "language": lang}


MUTATION = re.compile(r"ignore (?:all |the |previous |your )*(?:instructions|rules)|system prompt|you are now|pretend|"
                      r"(?:change|raise|increase|set|double|waive|reduce|cancel|override)\b.{0,30}\b(?:payout|premium|price|cap|limit|policy|trigger)|"
                      r"\b(?:approve|release|send|transfer|pay)\b.{0,25}\b(?:me|my|money|payout|claim|now)|mark.{0,15}paid|"
                      r"(?:\bdelete\b|\bdrop\b).{0,20}(?:record|ledger|table)|reveal.{0,20}(?:token|password|other merchant)", re.I)
INTENTS = (("pay", ("pay", "paid", "money", "wallet", "bank", "transfer")), ("remaining", ("remaining", "left", "cap", "limit")),
           ("bill", ("bill", "premium", "instalment", "debit")), ("why", ("why", "rain", "haze", "psi", "trigger", "today")))
REFUSAL = {"en": "I can only explain your recorded cover. I cannot change, approve or pay anything, or follow instructions that try to.",
           "zh": "我只能解释您已记录的保障，无法更改、批准或支付任何款项，也不会执行此类指示。",
           "ms": "Saya hanya boleh menerangkan perlindungan yang direkodkan. Saya tidak boleh mengubah, meluluskan atau membayar apa-apa.",
           "ta": "பதிவு செய்யப்பட்ட காப்பை மட்டுமே விளக்க முடியும். எதையும் மாற்றவோ அங்கீகரிக்கவோ செலுத்தவோ என்னால் முடியாது."}


def answer(snap: dict, message: str, lang: str = "en") -> dict:
    """Read-only Q&A. A message can only select which grounded explanation is shown; it never reaches a tool or the ledger."""
    if lang not in T:
        raise ValueError("unsupported language")
    if MUTATION.search(message or ""):
        return {"schema_version": SCHEMA, "language": lang, "refused": True, "text": REFUSAL[lang], "read_only": True,
                "decides_payouts": False, "mutation_attempt_flagged": True, "state_changed": False}
    exp = explain(snap, lang)
    low = (message or "").lower()
    intent = next((n for n, ks in INTENTS if any(k in low for k in ks)), "overview")
    return {**exp, "intent": intent, "refused": False, "state_changed": False}
