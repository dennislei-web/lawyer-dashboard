import sys,io,json,openpyxl
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
wb=openpyxl.load_workbook(r"C:\Users\admin\Downloads\帶走案件時費用規則 (1).xlsx",data_only=True)
def num(x):
    try: return int(float(x))
    except: return None

out={"_doc":"轉合署一次帶走案件結算。帶走金額一律 委任費*0.6（指定費不計入）；代庭 5000/庭。原委任費留所內，帶走金額=該律師轉合署當月一次性合署業績。",
     "_rule":{"帶走":"委任費*0.6","代庭":"5000/開庭次","交接/交回":"留所內"},"lawyers":{}}

# 蘇萱: cols 當事人,對造,案由,管轄,案件編號,委任費,律師指定費,帶走金額
ws=wb['蘇萱']; cases=[]; tot_fee=0
for r in ws.iter_rows(min_row=2,values_only=True):
    if not r or r[0] in (None,'合計') or num(r[6]) is None: continue
    fee=num(r[6])
    cases.append({"當事人":r[1],"案件編號":(str(num(r[5])) if num(r[5]) else None),"委任費":fee,"type":"轉合署","帶走金額":round(fee*0.6)})
    tot_fee+=fee
out["lawyers"]["蘇萱"]={"since":"2026-05-01","basis":"委任費","cases":cases,
    "委任費合計":tot_fee,"帶走金額合計":sum(c["帶走金額"] for c in cases)}

# 李家泓: 當事人,對造,案由,進度,委任費,轉合署/代庭,交接,調整
ws=wb['李家泓']; cases=[]; tot_fee_zhuan=0; daiting=0
for r in ws.iter_rows(min_row=2,values_only=True):
    if not r or not r[0]: continue
    typ=(r[5] or '').strip() if r[5] else ''
    fee=num(r[4])
    if '轉合署' in typ and '代庭' not in typ.replace('轉合署',''):
        if fee: cases.append({"當事人":r[0],"委任費":fee,"type":"轉合署","帶走金額":round(fee*0.6)}); tot_fee_zhuan+=fee
    elif '代庭' in typ:
        cases.append({"當事人":r[0],"委任費":fee,"type":"代庭","帶走金額":"5000/庭(庭次另計)"}); daiting+=1
    # 交接/交回(無type、有調整人名) 略過=留所內
out["lawyers"]["李家泓"]={"since":"2026-06-01","basis":"委任費","cases":cases,
    "轉合署委任費合計":tot_fee_zhuan,"帶走金額合計(轉合署)":round(tot_fee_zhuan*0.6),
    "代庭案數":daiting,"note":"代庭金額=5000*實際開庭次，需另計；交接/交回案留所內"}

# 吳柏慶: 客戶名稱,案件性質,給付比例,委任費(表頭誤寫"客戶已付款金額",實為委任費全額),諮詢費,應付金額
ws=wb['吳柏慶']; cases=[]; tot_fee=0
for r in ws.iter_rows(min_row=2,values_only=True):
    if not r or r[0] in (None,'合計') or num(r[4]) is None: continue
    fee=num(r[4])
    cases.append({"當事人":r[0],"委任費":fee,"type":"喆律轉案","帶走金額":round(fee*0.6)})
    tot_fee+=fee
out["lawyers"]["吳柏慶"]={"since":"2026-03-01","basis":"委任費","cases":cases,
    "委任費合計":tot_fee,"帶走金額合計":sum(c["帶走金額"] for c in cases),
    "note":"原表頭誤寫『客戶已付款金額』，實為委任費全額"}

open("scripts/partners/carryover_cases.json","w",encoding="utf-8").write(json.dumps(out,ensure_ascii=False,indent=2))
for n,d in out["lawyers"].items():
    k=[k for k in d if '帶走金額合計' in k or '帶走金額合計(轉合署)' in k]
    print(f"{n} (轉合署 {d['since']}): 帶走金額 {d.get('帶走金額合計') or d.get('帶走金額合計(轉合署)')}  | 案數 {len(d['cases'])} | basis={d['basis']}")
print("\nwrote scripts/partners/carryover_cases.json")
