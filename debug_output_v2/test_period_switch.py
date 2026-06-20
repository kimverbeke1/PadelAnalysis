import requests, time, re
from bs4 import BeautifulSoup
from xml.etree import ElementTree as ET

BASE_URL = "https://www.tennisenpadelvlaanderen.be"
HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
    "Accept-Language": "nl-BE,nl;q=0.9",
}
params = {"userId": "214435", "tab": "padel", "tspid": "80", "tdpid": "80", "ppid": "79", "tscid": "80", "pcid": "79"}

session = requests.Session()
r = session.get(BASE_URL + "/dashboard/resultaten", params=params, headers=HEADERS_BASE, timeout=30)
soup = BeautifulSoup(r.text, "html.parser")

P = "_player_complete_results_all_WAR_vtvportletportlet_"

# Find padel form by partial ID match
padel_form = soup.find("form", id=re.compile(r"playerCompleteResultsPadelF"))
print("Padel form found:", padel_form is not None)
if padel_form:
    print("  form id:", padel_form.get("id","")[:100])

# ViewState: find the one inside the padel form
vs_inputs = soup.find_all("input", {"name": "javax.faces.ViewState"})
print(f"Total ViewState inputs: {len(vs_inputs)}")
# The padel form's ViewState is the 3rd one (0=tennis enkel, 1=tennis dubbel, 2=padel)
padel_vs = vs_inputs[2] if len(vs_inputs) > 2 else None
print("Padel ViewState value:", padel_vs.get("value","")[:30] if padel_vs else "NOT FOUND")

# Ajax spinner div inside padel form -> get base ID
ajax_spinner_div = padel_form.find("div", id=re.compile(r"_start$")) if padel_form else None
ajax_base_id = ajax_spinner_div.get("id","").replace("_start","") if ajax_spinner_div else None
print("Ajax base div ID:", ajax_base_id)

select_name = P + "padelPeriod"

ajax_url = (
    BASE_URL + "/dashboard/resultaten"
    "?p_p_id=player_complete_results_all_WAR_vtvportletportlet"
    "&p_p_lifecycle=2&p_p_state=normal&p_p_mode=view"
    "&p_p_cacheability=cacheLevelPage&p_p_col_id=&p_p_col_count=0"
    "&_player_complete_results_all_WAR_vtvportletportlet__jsfBridgeAjax=true"
    "&_player_complete_results_all_WAR_vtvportletportlet__facesViewIdResource="
    "%2FWEB-INF%2Fviews%2Fdashboard%2Fplayer_results%2FplayerCompleteResultsAll.xhtml"
)

form_id = padel_form.get("id","") if padel_form else P + "playerCompleteResultsPadelForm"

form_data = {
    form_id: form_id,
    select_name: "77",
    "javax.faces.partial.ajax": "true",
    "javax.faces.source": select_name,
    "javax.faces.partial.execute": select_name,
    "javax.faces.partial.render": ajax_base_id or (P + "j_idt129"),
    "javax.faces.ViewState": padel_vs.get("value","") if padel_vs else "",
    "userId": "214435",
}

ajax_headers = {
    **HEADERS_BASE,
    "Accept": "application/xml, text/xml, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Faces-Request": "partial/ajax",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": r.url,
}

print(f"\nPOSTing AJAX, period=77 (week 27/2025-48/2025)...")
time.sleep(1.5)
resp = session.post(ajax_url, data=form_data, headers=ajax_headers, timeout=30)
print("Status:", resp.status_code, "  Length:", len(resp.text))

try:
    root = ET.fromstring(resp.text)
    for child in root.iter():
        if child.tag == "update":
            uid = child.get("id", "")
            cdata = child.text or ""
            print(f"\nUPDATE id=...{uid[-50:]}, content={len(cdata)} chars")
            if len(cdata) > 500:
                inner = BeautifulSoup(cdata, "html.parser")
                h4s = inner.find_all("h4", class_="details-box-title")
                orgs = inner.find_all("div", class_="tournament-organization")
                details = inner.find_all("div", class_="details")
                print(f"  h4.details-box-title={len(h4s)}, tournament-org={len(orgs)}, details={len(details)}")
                for h in h4s[:6]:
                    print("   ", h.get_text(strip=True))
except Exception as e:
    print("XML parse error:", e)
    print(resp.text[:500])
