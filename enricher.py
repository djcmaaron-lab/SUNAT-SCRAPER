import re, time, requests
from bs4 import BeautifulSoup

BASE_CCL  = "http://200.37.9.27/CCLDirectoriovirtual/"
POST_CCL  = "http://200.37.9.27/CCLDirectoriovirtual/?v=150"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "es-PE,es;q=0.9",
    "Referer": BASE_CCL,
}

EMAIL_RE    = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE    = re.compile(r"(?:\+?51\s*)?(?:\(?\d{1,3}\)?\s*)?[\d][\d\s\-\(\)]{5,}\d")
POSTBACK_RE = re.compile(r"__doPostBack\s*\(\s*['\"]([^'\"]*)['\"\s]*,\s*['\"]([^'\"]*)['\"]", re.I)

def _norm(t): return " ".join((t or "").split()).strip()
def _digits(s): return re.sub(r"\D", "", s or "")

def _clean_phones(text):
    out, seen = [], set()
    for m in PHONE_RE.findall(text or ""):
        p = _norm(m).strip("-=E2=80=93:;,. ")
        d = _digits(p)
        if len(d) < 7 or d in seen: continue
        seen.add(d); out.append(p)
    return out

def _session():
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    return s

def detectar_col_empresa(row):
    prioridad = ["empresa","nombre","name","razon_social","razon social","company","negocio","business"]
    keys_lower = {k.lower().strip(): k for k in row.keys()}
    for p in prioridad:
        if p in keys_lower and row[keys_lower[p]]:
            return str(row[keys_lower[p]])
    for v in row.values():
        if v and isinstance(v, str) and len(v) > 3:
            return v
    return ""

def detectar_col_rubro(row):
    prioridad = ["rubro","categoria","type","sector","industria","giro","category"]
    keys_lower = {k.lower().strip(): k for k in row.keys()}
    for p in prioridad:
        if p in keys_lower:
            return str(row[keys_lower[p]] or "")
    return ""

def detectar_col_ruc(row):
    prioridad = ["ruc","ruc/dni","documento","doc","tax_id","cif_detected","cif"]
    keys_lower = {k.lower().strip(): k for k in row.keys()}
    for p in prioridad:
        if p in keys_lower:
            v = str(row[keys_lower[p]] or "")
            if len(_digits(v)) >= 8:
                return v
    return ""

# ── CCL ──────────────────────────────────────────────────────────────────────

def _hidden(soup):
    f = {}
    for el in soup.select("input[name^='__VIEWSTATE'],textarea[name^='__VIEWSTATE']"):
        name = el.get("name")
        if name:
            f[name] = el.get("value","") if el.name=="input" else (el.get_text() or "")
    for n in ["__VIEWSTATEGENERATOR","__EVENTVALIDATION","__LASTFOCUS"]:
        el = soup.find(["input","textarea"], {"name": n})
        if el:
            f[n] = el.get("value","") if el.name=="input" else (el.get_text() or "")
    return f

def _base_form(hidden, rubro_id):
    d = {"__EVENTTARGET":"","__EVENTARGUMENT":"","__LASTFOCUS":hidden.get("__LASTFOCUS",""),
         "cboListaPadron":"1","cboPadron":str(rubro_id),"cboPadronSector":"0",
         "cboPadronSubSector":"0","cboPadronPartidas":"0","cboPadronRnkExp":"0",
         "cboPadronRnkImp":"0","cboPadronGuiaTop":"0","cboPadronGuiaEmail":"0",
         "filter":"","filter1":"","hdChk":"","hdChkSearch":""}
    for k,v in hidden.items():
        if k.startswith("__VIEWSTATE") or k in {"__VIEWSTATEGENERATOR","__EVENTVALIDATION"}:
            if v: d[k] = v
    return d

def get_rubros_ccl(session=None):
    session = session or _session()
    r = session.get(POST_CCL, timeout=20)
    soup = BeautifulSoup(r.text, "html.parser")
    sel = soup.find("select", {"name":"cboPadron"}) or soup.find("select", {"id":"cboPadron"})
    out = {}
    if sel:
        for opt in sel.find_all("option"):
            v = (opt.get("value") or "").strip()
            label = _norm(opt.get_text())
            if not v or v=="0" or label.upper()=="SELECCIONAR": continue
            out[label] = v
    return out

def scrape_rubros_ccl(rubros_lista):
    session = _session()
    rubro_map = get_rubros_ccl(session)
    results = []
    for rubro in rubros_lista:
        rubro_id = rubro_map.get(rubro)
        if not rubro_id:
            for k, v in rubro_map.items():
                if k.upper().strip() == rubro.upper().strip():
                    rubro_id = v; break
        if not rubro_id: continue
        try:
            r0 = session.get(POST_CCL, timeout=20)
            hidden0 = _hidden(BeautifulSoup(r0.text, "html.parser"))
            form = _base_form(hidden0, rubro_id)
            form["__EVENTTARGET"] = "lkBtnSearch"
            r1 = session.post(POST_CCL, data=form, timeout=20)
            soup1 = BeautifulSoup(r1.text, "html.parser")
            hidden1 = _hidden(soup1)
            pages = [(soup1, hidden1)]
            for a in soup1.find_all("a"):
                for src in [a.get("href",""), a.get("onclick","")]:
                    m = POSTBACK_RE.search(src)
                    if m and re.match(r"Page\$\d+", m.group(2), re.I):
                        form2 = _base_form(hidden1, rubro_id)
                        form2["__EVENTTARGET"] = m.group(1)
                        form2["__EVENTARGUMENT"] = m.group(2)
                        r2 = session.post(POST_CCL, data=form2, timeout=20)
                        s2 = BeautifulSoup(r2.text, "html.parser")
                        h2 = _hidden(s2)
                        pages.append((s2, h2))
                        hidden1 = h2
                        time.sleep(0.2)
            for pg, _ in pages:
                for t in pg.find_all("table"):
                    rows = t.find_all("tr")
                    names = []
                    for tr in rows:
                        tds = tr.find_all("td")
                        if len(tds) >= 2:
                            n = _norm(tds[-1].get_text())
                            if n and n.upper() not in {"EMPRESA","RAZÓN SOCIAL","RAZON SOCIAL","#"}:
                                names.append(n)
                    if names:
                        for nombre in names:
                            results.append({"empresa": nombre, "rubro": rubro})
                        break
            time.sleep(0.3)
        except Exception:
            continue
    return results

# ── SUNAT ────────────────────────────────────────────────────────────────────

def buscar_ruc_por_nombre(nombre, session=None):
    session = session or _session()
    try:
        url = f"https://api.apis.net.pe/v2/sunat/ruc/buscar?razonSocial={requests.utils.quote(nombre)}"
        r = session.get(url, timeout=12)
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, list): return d[:5]
            if isinstance(d, dict) and "data" in d: return d["data"][:5]
    except Exception:
        pass
    return []

def obtener_datos_ruc(ruc, session=None):
    session = session or _session()
    try:
        url = f"https://api.apis.net.pe/v2/sunat/ruc?numero={ruc}"
        r = session.get(url, timeout=12)
        if r.status_code == 200:
            d = r.json()
            result = {
                "ruc":                 d.get("numeroDocumento", ruc),
                "razon_social":        d.get("nombre",""),
                "tipo":                d.get("tipoContribuyente",""),
                "estado":              d.get("estado",""),
                "condicion":           d.get("condicion",""),
                "fecha_inscripcion":   d.get("fechaInscripcion","") or d.get("fechaRegistro",""),
                "fecha_inicio_act":    d.get("fechaInicioActividades","") or d.get("fechaActividadComercial",""),
                "actividad_economica": d.get("actividadEconomica","") or d.get("ciiu",""),
                "direccion":           d.get("direccion",""),
                "departamento":        d.get("departamento",""),
                "provincia":           d.get("provincia",""),
                "distrito":            d.get("distrito",""),
                "telefono":            "",
                "email":               "",
                "representante":       "",
                "cargo_rep":           "",
                "todos_representantes":"",
                "fuente":              "SUNAT/apis.net.pe",
            }
            reps = d.get("representantes") or d.get("representantesList") or []
            if reps:
                result["representante"] = reps[0].get("nombre","")
                result["cargo_rep"]     = reps[0].get("cargo","")
                todos = [f"{rep.get('nombre','')} [{rep.get('cargo','')}]" for rep in reps]
                result["todos_representantes"] = " | ".join(todos)
            tel = d.get("telefono") or d.get("telefonos") or ""
            if tel:
                result["telefono"] = tel if isinstance(tel, str) else " / ".join(tel)
            return result
    except Exception:
        pass
    return {}

def scrape_sunat_ruc(ruc, session=None):
    session = session or _session()
    try:
        url = f"https://e-consultaruc.sunat.gob.pe/cl-ti-itmrconsruc/jcrS00Alias?accion=consPorRuc&nroRuc={ruc}"
        r = session.get(url, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        result = {"ruc": ruc, "fuente": "SUNAT_directo"}
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2: continue
            lbl = _norm(cells[0].get_text()).upper()
            val = _norm(cells[1].get_text())
            if not val: continue
            if   "RAZON" in lbl or "NOMBRE" in lbl:   result["razon_social"]        = val
            elif "DIREC" in lbl:                       result["direccion"]           = val
            elif "ESTADO" in lbl:                      result["estado"]              = val
            elif "CONDIC" in lbl:                      result["condicion"]           = val
            elif "TIPO" in lbl and "CONTRIB" in lbl:   result["tipo"]                = val
            elif "DEPARTAM" in lbl:                    result["departamento"]        = val
            elif "PROVIN" in lbl:                      result["provincia"]           = val
            elif "DISTRIT" in lbl:                     result["distrito"]            = val
            elif "TELEF" in lbl:                       result["telefono"]            = val
            elif "REPRES" in lbl or "GERENT" in lbl:   result["representante"]       = val
            elif "FECHA" in lbl and "INSCR" in lbl:    result["fecha_inscripcion"]   = val
            elif "FECHA" in lbl and "INICIO" in lbl:   result["fecha_inicio_act"]    = val
            elif "ACTIVIDAD" in lbl:                   result["actividad_economica"] = val
        return result
    except Exception:
        return {}

# ── Páginas Amarillas ─────────────────────────────────────────────────────────

def buscar_paginas_amarillas(nombre, session=None):
    session = session or _session()
    try:
        q = requests.utils.quote(nombre)
        r = session.get(f"https://www.paginasamarillas.com.pe/busqueda/{q}/", timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        listing = (soup.find("div", class_=re.compile(r"listing|result|empresa", re.I))
                   or soup.find("article")
                   or soup.find("li", class_=re.compile(r"item|result", re.I)))
        if not listing: return {}
        text = _norm(listing.get_text(" "))
        phones = _clean_phones(text)
        emails = EMAIL_RE.findall(text)
        addr = ""
        for el in listing.find_all(["span","div","p"]):
            cls = " ".join(el.get("class") or []).lower()
            if any(k in cls for k in ["addr","dir","address","ubic"]):
                addr = _norm(el.get_text()); break
        return {"telefono_pa":" / ".join(phones[:3]),"email_pa":emails[0] if emails else "","direccion_pa":addr}
    except Exception:
        return {}

def buscar_duckduckgo(nombre, session=None):
    session = session or _session()
    try:
        q = requests.utils.quote(f"{nombre} Lima Peru telefono contacto")
        r = session.get(f"https://html.duckduckgo.com/html/?q={q}", timeout=12,
                        headers={**DEFAULT_HEADERS, "Accept": "text/html"})
        text = _norm(BeautifulSoup(r.text, "html.parser").get_text(" "))
        phones = _clean_phones(text)
        emails = EMAIL_RE.findall(text)
        return {"telefono_ddg":" / ".join(phones[:2]),"email_ddg":emails[0] if emails else ""}
    except Exception:
        return {}

# ── ENRIQUECEDOR PRINCIPAL ────────────────────────────────────────────────────

CAMPOS_SALIDA = [
    "empresa","rubro","ruc","razon_social","tipo","estado","condicion",
    "fecha_inscripcion","fecha_inicio_act","actividad_economica",
    "representante","cargo_rep","todos_representantes",
    "telefono","email","direccion","departamento","provincia","distrito",
    "tel_original","email_original","ciudad","score","priority","fuentes",
]

def enriquecer_empresa(nombre, rubro="", ruc_conocido="", datos_extra=None):
    s = _session()
    result = {c: "" for c in CAMPOS_SALIDA}
    result["empresa"] = nombre
    result["rubro"]   = rubro
    result["ruc"]     = ruc_conocido
    fuentes = []

    ruc = _digits(ruc_conocido)[:11] if ruc_conocido else ""

    # 1. Buscar RUC
    if not ruc:
        candidatos = buscar_ruc_por_nombre(nombre, s)
        if candidatos:
            ruc = candidatos[0].get("numeroDocumento") or candidatos[0].get("ruc") or ""
            ruc = _digits(str(ruc))[:11]
            if ruc:
                result["ruc"] = ruc
                fuentes.append("SUNAT_busqueda")
        time.sleep(0.3)

    # 2. Datos por RUC
    if ruc:
        datos = obtener_datos_ruc(ruc, s)
        if not datos.get("razon_social"):
            datos = scrape_sunat_ruc(ruc, s)
        for c in ["razon_social","tipo","estado","condicion","fecha_inscripcion",
                  "fecha_inicio_act","actividad_economica","representante","cargo_rep",
                  "todos_representantes","direccion","departamento","provincia","distrito","telefono"]:
            if datos.get(c): result[c] = datos[c]
        if datos.get("fuente"): fuentes.append(datos["fuente"])
        time.sleep(0.35)

    # 3. Páginas Amarillas
    if not result["telefono"] or not result["email"]:
        pa = buscar_paginas_amarillas(nombre, s)
        if pa.get("telefono_pa") and not result["telefono"]: result["telefono"]  = pa["telefono_pa"]
        if pa.get("email_pa")    and not result["email"]:    result["email"]     = pa["email_pa"]
        if pa.get("direccion_pa")and not result["direccion"]:result["direccion"] = pa["direccion_pa"]
        if any(pa.values()): fuentes.append("PaginasAmarillas")
        time.sleep(0.3)

    # 4. DuckDuckGo
    if not result["telefono"] and not result["email"]:
        dd = buscar_duckduckgo(nombre, s)
        if dd.get("telefono_ddg"): result["telefono"] = dd["telefono_ddg"]
        if dd.get("email_ddg"):    result["email"]    = dd["email_ddg"]
        if any(dd.values()): fuentes.append("DuckDuckGo")
        time.sleep(0.3)

    # Preservar datos originales del Excel
    if datos_extra:
        result["tel_original"]   = str(datos_extra.get("phone","") or datos_extra.get("telefono","") or "")
        result["email_original"] = str(datos_extra.get("emails","") or datos_extra.get("email","") or "")
        result["ciudad"]         = str(datos_extra.get("city","") or datos_extra.get("ciudad","") or "")
        result["score"]          = str(datos_extra.get("lead_score","") or datos_extra.get("score","") or "")
        result["priority"]       = str(datos_extra.get("priority","") or datos_extra.get("prioridad","") or "")

    result["fuentes"] = " | ".join(fuentes)
    return result


def enriquecer_lote(empresas: list, progress_cb=None) -> list:
    total, results = len(empresas), []
    for idx, item in enumerate(empresas, 1):
        nombre = detectar_col_empresa(item)
        rubro  = detectar_col_rubro(item)
        ruc    = detectar_col_ruc(item)
        if not nombre: continue
        try:
            data   = enriquecer_empresa(nombre, rubro, ruc, datos_extra=item)
            status = "ok"
        except Exception as e:
            data   = {c:"" for c in CAMPOS_SALIDA}
            data.update({"empresa":nombre,"rubro":rubro,"fuentes":f"ERROR: {e}"})
            status = "error"
        results.append(data)
        if progress_cb:
            progress_cb({
                "index":idx,"total":total,"empresa":nombre,"status":status,
                "con_rep":  sum(1 for r in results if r.get("representante")),
                "con_tel":  sum(1 for r in results if r.get("telefono")),
                "con_email":sum(1 for r in results if r.get("email")),
                "progress": int(idx/total*100),
            })
    return results
