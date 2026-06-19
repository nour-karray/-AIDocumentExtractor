from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.services.document_router import detect_document_type, process_any_document
from src.web.history_views import render_quality_and_warnings_section
from src.web.extraction_workspace_ui import (
    inject_extraction_workspace_styles,
    render_alert_error,
    render_batch_summary,
    render_document_header,
    render_file_queue_cards,
    render_guided_stepper,
    render_medical_gemini_results,
    render_medical_ocr_results,
    render_pipeline_timeline,
    render_receipt_results,
    render_steg_results,
    render_supplier_results,
    render_upload_section_title,
    render_workspace_hero,
    resolve_pipeline_steps,
)
from src.web.ui_theme import inject_app_styles, inject_page_theme
from pipelines.extract_medical_report_gemini import extract_medical_report
from pipelines.extract_receipt_gemini import extract_receipt
from pipelines.extract_supplier_invoice_gemini import extract_supplier_invoice


@contextmanager
def _gemini_env(api_key: str):
    old = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = api_key
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = old


def _try_process_document(
    tmp_path: Path,
    mode: str,
    *,
    use_gemini: bool = False,
    gemini_model: str | None = None,
) -> tuple[dict | None, str | None]:
    """Retourne (routed, processing_error)."""
    try:
        routed = process_any_document(
            tmp_path,
            mode=mode,
            use_gemini=use_gemini,
            gemini_api_key=None,
            gemini_model=gemini_model,
        )
        return routed, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _choose_local_folder_dialog(initial_dir: str | None = None) -> tuple[str | None, str | None]:
    """Ouvre le selecteur natif Windows pour choisir un dossier local."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        return None, f"Selecteur de dossier indisponible: {exc}"

    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            initialdir=initial_dir or str(Path.home()),
            title="Choisir un dossier",
            mustexist=True,
        )
        root.destroy()
    except Exception as exc:
        return None, f"Impossible d'ouvrir le selecteur de dossier: {exc}"

    if selected:
        return selected, None
    return None, None


st.set_page_config(page_title="Extraction documents", layout="wide")
inject_app_styles(show_theme_toggle=False)
inject_extraction_workspace_styles(dark=bool(st.session_state.get("hx_dark_mode")))
inject_page_theme("extraction")
st.sidebar.caption(
    "Extractions enregistrées automatiquement. Consultez **Historiques** dans le menu."
)

cfg = load_config()

_MODE_OPTIONS = [
    "Auto (detection)",
    "Analyse medicale",
    "Facture STEG",
    "Facture fournisseur (generique)",
    "Ticket de caisse",
]
_METHOD_OPTIONS = ["Gemini (API)", "OCR local (sans API)"]
if "hx_ext_mode_label" not in st.session_state:
    st.session_state["hx_ext_mode_label"] = _MODE_OPTIONS[0]
if "hx_ext_method_label" not in st.session_state:
    st.session_state["hx_ext_method_label"] = _METHOD_OPTIONS[0]

render_workspace_hero(
    mode_label=st.session_state["hx_ext_mode_label"],
    extraction_method=st.session_state["hx_ext_method_label"],
    dark=bool(st.session_state.get("hx_dark_mode")),
    api_ready=bool(
        st.session_state.get("hx_gemini_api_input")
        or cfg.gemini_api_key
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    ),
)
config_col, upload_col = st.columns([1.0, 1.65], gap="large")

with config_col:
    st.markdown("### Etape 2 - Configurer")
    st.caption(
        "Choisis le type, la methode et la cle Gemini ici. Le pipeline reste strictement le meme."
    )
    st.toggle(
        "Theme noir",
        key="hx_dark_mode",
        help="Bascule l'interface complete entre rendu noir et rendu blanc.",
    )
    st.markdown('<span style="font-size:11px;font-weight:700;opacity:.85;">Raccourcis pipeline</span>', unsafe_allow_html=True)
    r1, r2, r3 = st.columns(3)
    with r1:
        if st.button("✨ Auto", key="hx_sc_auto", use_container_width=True, help="Détection automatique du type"):
            st.session_state["hx_ext_mode_label"] = "Auto (detection)"
            st.rerun()
    with r2:
        if st.button("🧠 Gemini", key="hx_sc_gem", use_container_width=True, help="Extraction via API Gemini"):
            st.session_state["hx_ext_method_label"] = "Gemini (API)"
            st.rerun()
    with r3:
        if st.button(
            "🔍 OCR",
            key="hx_sc_ocr",
            use_container_width=True,
            help="OCR local sans API (incompatible ticket / facture fournisseur — utilisez Gemini ou un autre type).",
        ):
            st.session_state["hx_ext_method_label"] = "OCR local (sans API)"
            st.rerun()
    mode_label = st.radio(
        "Type de document",
        options=_MODE_OPTIONS,
        key="hx_ext_mode_label",
        help="Auto : devine facture STEG, ticket, facture fournisseur ou analyse medicale (nom du fichier + OCR "
        "Tesseract ara/eng et texte PDF si disponible), puis extraction Gemini. Sinon : type impose.",
    )
    mode_map = {
        "Auto (detection)": "auto",
        "Analyse medicale": "medical",
        "Facture STEG": "steg",
        "Facture fournisseur (generique)": "supplier",
        "Ticket de caisse": "receipt",
    }
    mode = mode_map[mode_label]

    st.caption(
        "Choisissez la methode d'extraction : Gemini (avec cle API) ou OCR local (sans API). "
        "Le ticket de caisse reste Gemini uniquement."
    )
    extraction_method = st.radio(
        "Methode d'extraction",
        options=_METHOD_OPTIONS,
        key="hx_ext_method_label",
    )
    use_local_ocr = extraction_method.startswith("OCR local")

    if mode in ("receipt", "supplier") and use_local_ocr:
        st.session_state["hx_ext_method_label"] = _METHOD_OPTIONS[0]
        st.info(
            "**Ticket** et **facture fournisseur** nécessitent Gemini (API). "
            "La méthode a été basculée automatiquement."
        )
        st.rerun()
    if mode == "auto" and use_local_ocr:
        st.info(
            "En **Auto** avec **OCR local**, un fichier détecté comme **ticket** ou **facture fournisseur** ne pourra pas être extrait. "
            "Utilisez **Gemini (API)** (bouton 🧠) ou imposez un autre type (STEG, médical)."
        )

    st.subheader("Gemini")
    key_default = cfg.gemini_api_key or ""
    api_key = st.text_input(
        "Cle API Gemini",
        value=key_default,
        key="hx_gemini_api_input",
        type="password",
        help="Obtenir une cle : https://aistudio.google.com/apikey — ou variable GEMINI_API_KEY dans .env",
    )
    if (api_key or "").strip():
        st.success("Cle Gemini chargee pour cette session.")
    else:
        st.info("Tu peux aussi la mettre de facon permanente dans `.env` avec `GEMINI_API_KEY=...`.")
    model = st.text_input(
        "Modele",
        value=cfg.gemini_model,
        help="Recommande : gemini-2.5-flash. Les anciens noms gemini-1.5-* sont remappes ou remplaces automatiquement si l'API renvoie 404.",
    )
    retries = st.number_input("Retries Gemini", min_value=1, max_value=10, value=5, step=1)
    retry_delay = st.number_input("Retry delay (sec)", min_value=0.5, max_value=10.0, value=2.0, step=0.5)
    st.caption(
        "Sans cle Gemini : echec pour l'analyse medicale, la facture STEG, la facture fournisseur et le ticket."
    )

with upload_col:
    render_upload_section_title()
upload_col.markdown(
    '<div class="hx-guided-note"><b>Ou mettre la cle Gemini ?</b><br/>'
    "Tu peux la coller dans le panneau de configuration pour cette session, ou la stocker dans "
    "<code>.env</code> avec <code>GEMINI_API_KEY=...</code>.</div>",
    unsafe_allow_html=True,
)
upload_col.markdown('<div class="hx-xp-upload-shell hx-fade-in"><div class="hx-xp-upload-shell-inner">', unsafe_allow_html=True)
uploaded_files = upload_col.file_uploader(
    "Glissez vos documents ici ou cliquez pour parcourir",
    type=["jpg", "jpeg", "png", "tif", "tiff", "pdf"],
    accept_multiple_files=True,
    label_visibility="visible",
)
action_left, action_right = upload_col.columns([4.0, 1.2], vertical_alignment="center")
with action_left:
    st.caption("Astuce : images nettes et bien cadrées pour de meilleurs résultats OCR / vision.")
with action_right:
    process_folder = st.button(
        "📁 Dossier local",
        type="secondary",
        use_container_width=True,
        help="Importer tous les fichiers compatibles d'un dossier (traitement en mode Auto).",
    )
upload_col.markdown("</div></div>", unsafe_allow_html=True)

allowed_exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".pdf"}
docs_to_process: list[dict[str, bytes | str]] = []

if uploaded_files:
    for f in uploaded_files:
        docs_to_process.append({"name": f.name, "bytes": f.getvalue(), "origin": "upload"})

if process_folder:
    picked, picker_error = _choose_local_folder_dialog()
    if picker_error:
        st.error(picker_error)
    elif not picked:
        st.info("Selection du dossier annulee.")
    else:
        base = Path(picked)
        added = 0
        failed = 0
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in allowed_exts:
                continue
            try:
                docs_to_process.append(
                    {
                        "name": p.name,
                        "bytes": p.read_bytes(),
                        "origin": str(p.parent),
                    }
                )
                added += 1
            except OSError:
                failed += 1
        if added > 0:
            st.success(f"{added} fichier(s) charge(s) depuis `{picked}`.")
        if failed > 0:
            st.warning(f"{failed} fichier(s) ignore(s) (lecture impossible).")
        if added == 0:
            st.info("Aucun fichier compatible trouve dans ce dossier.")

render_guided_stepper(
    docs_count=len(docs_to_process),
    config_ready=bool(use_local_ocr or (api_key or "").strip() or cfg.gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
)

if docs_to_process:
    st.markdown(
        f"**Lot sélectionné** · {len(docs_to_process)} fichier(s) — pipeline prêt à s'exécuter.",
    )
    render_file_queue_cards(list(docs_to_process))
    gkey = (api_key or "").strip() or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    batch_rows = []
    progress = st.progress(0.0, text="Initialisation du pipeline…")
    progress_label = st.empty()
    ok_count = 0
    err_count = 0

    for i, doc in enumerate(docs_to_process, start=1):
        progress_label.caption(f"Traitement intelligent en cours: {i}/{len(docs_to_process)}")
        progress.progress(i / len(docs_to_process), text=f"Pipeline AI: {i}/{len(docs_to_process)}")
        uploaded_name = str(doc["name"])
        uploaded_bytes = doc["bytes"]
        source_origin = str(doc.get("origin") or "upload")
        st.divider()
        render_document_header(index=i, filename=uploaded_name, source_origin=source_origin)
        suffix = Path(uploaded_name).suffix.lower() or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_bytes)
            tmp_path = Path(tmp.name)

        routed = None
        processing_error: str | None = None
        gemini_generic_result = None
        gemini_generic_error = None
        gemini_receipt_result = None
        gemini_receipt_error = None
        gemini_supplier_result = None
        gemini_supplier_error = None
        detected_kind = "inconnu"

        with st.spinner(f"Analyse en cours : {uploaded_name}"):
            effective_mode = "auto" if source_origin != "upload" else mode
            is_receipt_mode = effective_mode == "receipt"

            if is_receipt_mode and use_local_ocr:
                gemini_receipt_error = "Ticket de caisse : OCR local non disponible, utilisez Gemini."
            elif is_receipt_mode and not gkey:
                gemini_receipt_error = "Aucune cle Gemini detectee (GEMINI_API_KEY)."
            elif is_receipt_mode and suffix == ".pdf":
                gemini_receipt_error = (
                    "Pour un ticket, importez une image (JPG, PNG, TIFF, WebP), pas un PDF."
                )
            elif is_receipt_mode:
                with _gemini_env(gkey):
                    try:
                        gemini_receipt_result = extract_receipt(
                            tmp_path,
                            model=model.strip() if model else None,
                            retries=int(retries),
                            retry_delay_sec=float(retry_delay),
                        )
                        detected_kind = "receipt"
                    except Exception as exc:
                        gemini_receipt_error = str(exc)
            elif effective_mode == "steg":
                if use_local_ocr:
                    routed, processing_error = _try_process_document(
                        tmp_path,
                        "steg",
                        use_gemini=False,
                        gemini_model=None,
                    )
                    if routed is not None:
                        detected_kind = routed.get("doc_type") or "steg_invoice"
                elif not gkey:
                    processing_error = "Cle API Gemini requise pour l'extraction STEG (vision)."
                elif suffix == ".pdf":
                    processing_error = (
                        "Pour STEG avec Gemini, importez une image (JPG, PNG, TIFF, WebP), pas un PDF."
                    )
                else:
                    with _gemini_env(gkey):
                        routed, processing_error = _try_process_document(
                            tmp_path,
                            "steg",
                            use_gemini=True,
                            gemini_model=model.strip() if model else None,
                        )
                        if routed is not None:
                            detected_kind = routed.get("doc_type") or "steg_invoice"
            elif effective_mode == "supplier":
                detected_kind = "supplier_invoice"
                if use_local_ocr:
                    gemini_supplier_error = (
                        "Facture fournisseur : OCR local non disponible, utilisez Gemini."
                    )
                elif not gkey:
                    gemini_supplier_error = (
                        "Aucune cle Gemini detectee (GEMINI_API_KEY ou GOOGLE_API_KEY)."
                    )
                elif suffix not in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".pdf", ".webp"}:
                    gemini_supplier_error = "Format non supporte (utilisez une image ou un PDF)."
                else:
                    with _gemini_env(gkey):
                        try:
                            gemini_supplier_result = extract_supplier_invoice(
                                tmp_path,
                                model=model.strip() if model else None,
                                retries=int(retries),
                                retry_delay_sec=float(retry_delay),
                            )
                        except Exception as exc:
                            gemini_supplier_error = str(exc)
            elif effective_mode == "auto":
                doc_kind = "medical_lab_report"
                try:
                    doc_kind = detect_document_type(
                        tmp_path,
                        filename_hint=uploaded_name,
                        path_hint=source_origin,
                    )
                    detected_kind = doc_kind
                except Exception:
                    doc_kind = "medical_lab_report"
                    detected_kind = doc_kind

                if doc_kind == "steg_invoice":
                    if use_local_ocr:
                        routed, processing_error = _try_process_document(
                            tmp_path,
                            "steg",
                            use_gemini=False,
                            gemini_model=None,
                        )
                    elif not gkey:
                        processing_error = "Cle API Gemini requise pour l'extraction STEG (vision)."
                    elif suffix == ".pdf":
                        processing_error = (
                            "Pour STEG avec Gemini, importez une image (JPG, PNG, TIFF, WebP), pas un PDF."
                        )
                    else:
                        with _gemini_env(gkey):
                            routed, processing_error = _try_process_document(
                                tmp_path,
                                "steg",
                                use_gemini=True,
                                gemini_model=model.strip() if model else None,
                            )
                elif doc_kind == "receipt":
                    if use_local_ocr:
                        gemini_receipt_error = "Ticket de caisse : OCR local non disponible, utilisez Gemini."
                    elif not gkey:
                        gemini_receipt_error = "Aucune cle Gemini detectee (GEMINI_API_KEY)."
                    elif suffix == ".pdf":
                        gemini_receipt_error = (
                            "Pour un ticket, importez une image (JPG, PNG, TIFF, WebP), pas un PDF."
                        )
                    else:
                        with _gemini_env(gkey):
                            try:
                                gemini_receipt_result = extract_receipt(
                                    tmp_path,
                                    model=model.strip() if model else None,
                                    retries=int(retries),
                                    retry_delay_sec=float(retry_delay),
                                )
                            except Exception as exc:
                                gemini_receipt_error = str(exc)
                elif doc_kind == "supplier_invoice":
                    if use_local_ocr:
                        gemini_supplier_error = (
                            "Facture fournisseur : OCR local non disponible, utilisez Gemini."
                        )
                    elif not gkey:
                        gemini_supplier_error = (
                            "Aucune cle Gemini detectee (GEMINI_API_KEY ou GOOGLE_API_KEY)."
                        )
                    elif suffix not in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".pdf", ".webp"}:
                        gemini_supplier_error = "Format non supporte (utilisez une image ou un PDF)."
                    else:
                        with _gemini_env(gkey):
                            try:
                                gemini_supplier_result = extract_supplier_invoice(
                                    tmp_path,
                                    model=model.strip() if model else None,
                                    retries=int(retries),
                                    retry_delay_sec=float(retry_delay),
                                )
                            except Exception as exc:
                                gemini_supplier_error = str(exc)
                elif use_local_ocr:
                    routed, processing_error = _try_process_document(
                        tmp_path,
                        "medical",
                        use_gemini=False,
                        gemini_model=None,
                    )
                elif not gkey:
                    gemini_generic_error = "Aucune cle Gemini detectee (GEMINI_API_KEY)."
                else:
                    with _gemini_env(gkey):
                        try:
                            gemini_generic_result = extract_medical_report(
                                tmp_path,
                                model=model.strip() if model else None,
                                retries=int(retries),
                                retry_delay_sec=float(retry_delay),
                            )
                        except Exception as exc:
                            gemini_generic_error = str(exc)
            elif effective_mode == "medical":
                detected_kind = "medical_lab_report"
                if use_local_ocr:
                    routed, processing_error = _try_process_document(
                        tmp_path,
                        "medical",
                        use_gemini=False,
                        gemini_model=None,
                    )
                elif not gkey:
                    gemini_generic_error = "Aucune cle Gemini detectee (GEMINI_API_KEY)."
                else:
                    with _gemini_env(gkey):
                        try:
                            gemini_generic_result = extract_medical_report(
                                tmp_path,
                                model=model.strip() if model else None,
                                retries=int(retries),
                                retry_delay_sec=float(retry_delay),
                            )
                        except Exception as exc:
                            gemini_generic_error = str(exc)
            else:
                processing_error = f"Mode non pris en charge : {effective_mode!r}"

        batch_status = "erreur"
        if gemini_receipt_result is not None:
            batch_status = "ok"
        elif gemini_supplier_result is not None:
            batch_status = "ok"
        elif gemini_generic_result is not None:
            batch_status = "ok"
        elif routed is not None and processing_error is None:
            batch_status = "ok"

        render_pipeline_timeline(
            step_status=resolve_pipeline_steps(
                batch_status=batch_status,
                gemini_receipt_error=gemini_receipt_error,
                gemini_supplier_error=gemini_supplier_error,
                gemini_generic_error=gemini_generic_error,
                processing_error=processing_error,
            )
        )

        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

        status = "erreur"
        history_saved: Path | None = None

        if gemini_receipt_error is not None:
            _hint = ""
            if "OCR local" in gemini_receipt_error or "sans API" in gemini_receipt_error:
                _hint = (
                    " → Dans la barre latérale : Méthode d'extraction → Gemini (API), ou raccourci « Gemini »."
                )
            render_alert_error(f"Ticket (Gemini) : {gemini_receipt_error}{_hint}")
        elif gemini_receipt_result is not None:
            status = "ok"
            render_quality_and_warnings_section(gemini_receipt_result)
            render_receipt_results(
                gemini_receipt_result,
                uploaded_name=uploaded_name,
                effective_mode_auto=(effective_mode == "auto"),
            )
        elif gemini_supplier_error is not None:
            _hint = ""
            if "OCR local" in gemini_supplier_error or "sans API" in gemini_supplier_error:
                _hint = (
                    " → Dans la barre latérale : Méthode d'extraction → Gemini (API), ou raccourci « Gemini »."
                )
            render_alert_error(f"Facture fournisseur (Gemini) : {gemini_supplier_error}{_hint}")
        elif gemini_supplier_result is not None:
            status = "ok"
            render_quality_and_warnings_section(gemini_supplier_result)
            render_supplier_results(
                gemini_supplier_result,
                uploaded_name=uploaded_name,
                json_download_key=f"dl_supplier_json_{i}_{Path(uploaded_name).stem}",
                effective_mode_auto=(effective_mode == "auto"),
            )
        elif gemini_generic_error is not None:
            render_alert_error(f"Analyse médicale (Gemini) : {gemini_generic_error}")
        elif gemini_generic_result is not None:
            status = "ok"
            render_quality_and_warnings_section(gemini_generic_result)
            render_medical_gemini_results(gemini_generic_result)
        elif processing_error is not None:
            render_alert_error(f"Extraction : {processing_error}")
        elif routed is not None:
            status = "ok"
            if routed["kind"] == "steg":
                s = routed["result"]
                render_quality_and_warnings_section(s)
                render_steg_results(s)
            else:
                result = routed["result"]
                render_quality_and_warnings_section(result.model_dump())
                render_medical_ocr_results(result)
        else:
            st.warning("Aucun résultat d'extraction (état inattendu).")

        try:
            from src.services.extraction_history import save_extraction

            if status == "ok":
                if gemini_receipt_result is not None:
                    history_saved = save_extraction(
                        cfg,
                        "receipt",
                        uploaded_name,
                        gemini_receipt_result,
                        source_bytes=uploaded_bytes,
                    )
                elif gemini_supplier_result is not None:
                    history_saved = save_extraction(
                        cfg,
                        "supplier_invoice",
                        uploaded_name,
                        gemini_supplier_result,
                        source_bytes=uploaded_bytes,
                    )
                elif gemini_generic_result is not None:
                    history_saved = save_extraction(
                        cfg,
                        "medical_gemini",
                        uploaded_name,
                        gemini_generic_result,
                        source_bytes=uploaded_bytes,
                    )
                elif routed is not None:
                    if routed["kind"] == "steg":
                        s = routed["result"]
                        es = str((s.get("extraction_source") or "ocr")).lower()
                        steg_kind = "steg_gemini" if es == "gemini" else "steg_ocr"
                        history_saved = save_extraction(
                            cfg,
                            steg_kind,
                            uploaded_name,
                            s,
                            source_bytes=uploaded_bytes,
                        )
                    elif routed["kind"] == "medical":
                        history_saved = save_extraction(
                            cfg,
                            "medical_ocr",
                            uploaded_name,
                            routed["result"].model_dump(),
                            source_bytes=uploaded_bytes,
                        )
        except Exception as exc:
            st.caption(f"Historique : enregistrement impossible ({exc}).")

        if history_saved is not None:
            try:
                rel = history_saved.relative_to(cfg.project_root)
                st.success(f"Extraction enregistree : `{rel}`")
            except ValueError:
                st.success(f"Extraction enregistree : `{history_saved}`")

        if status == "ok":
            try:
                from src.services.extraction_report_pdf import build_extraction_report_pdf

                report_doc: dict | None = None
                report_kind = ""
                if history_saved is not None and history_saved.is_file():
                    report_doc = json.loads(history_saved.read_text(encoding="utf-8"))
                    report_kind = str((report_doc.get("_meta") or {}).get("kind") or "")
                else:
                    now = datetime.now(timezone.utc).isoformat()
                    meta = {"saved_at": now, "source_filename": uploaded_name, "kind": ""}
                    if gemini_receipt_result is not None:
                        report_kind = "receipt"
                        meta["kind"] = report_kind
                        report_doc = {**gemini_receipt_result, "_meta": meta}
                    elif gemini_supplier_result is not None:
                        report_kind = "supplier_invoice"
                        meta["kind"] = report_kind
                        report_doc = {**gemini_supplier_result, "_meta": meta}
                    elif gemini_generic_result is not None:
                        report_kind = "medical_gemini"
                        meta["kind"] = report_kind
                        report_doc = {**gemini_generic_result, "_meta": meta}
                    elif routed is not None:
                        if routed["kind"] == "steg":
                            s = routed["result"]
                            es = str((s.get("extraction_source") or "ocr")).lower()
                            report_kind = "steg_gemini" if es == "gemini" else "steg_ocr"
                            meta["kind"] = report_kind
                            report_doc = {**s, "_meta": meta}
                        elif routed["kind"] == "medical":
                            report_kind = "medical_ocr"
                            meta["kind"] = report_kind
                            report_doc = {**routed["result"].model_dump(), "_meta": meta}

                if report_doc and report_kind:
                    rep_pdf = build_extraction_report_pdf(report_doc, report_kind)
                    st.download_button(
                        "Telecharger rapport PDF (DOCEXTRACT)",
                        data=rep_pdf,
                        file_name=f"DOCEXTRACT_{Path(uploaded_name).stem}.pdf",
                        mime="application/pdf",
                        key=f"extract_report_{i}_{Path(uploaded_name).stem}",
                    )
            except Exception as exc:
                st.caption(f"Rapport PDF indisponible ({exc}). pip install reportlab")

        batch_rows.append(
            {
                "Fichier": uploaded_name,
                "Statut": status,
                "Type detecte": detected_kind,
                "Source": source_origin,
            }
        )
        if status == "ok":
            ok_count += 1
        else:
            err_count += 1

    st.divider()
    render_batch_summary(batch_rows, ok_count=ok_count, err_count=err_count)
