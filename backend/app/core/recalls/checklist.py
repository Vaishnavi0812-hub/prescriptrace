"""Physical-verification checklist shown with recall/alert results.

PrescripTrace does NOT detect fake medicines. This checklist helps staff inspect a pack. Each item
names its source; items without an official source are labelled as general good practice.
"""

from __future__ import annotations

from dataclasses import dataclass

CDSCO_GUIDANCE = (
    "https://cdsco.gov.in/opencms/export/sites/CDSCO_WEB/Pdf-documents/"
    "Guidance-for-Identification-and-Verification-of-Spurious-Drugs.pdf"
)
CDSCO_QR_FAQ = (
    "https://cdsco.gov.in/opencms/resources/UploadCDSCOWeb/2018/UploadPublic_NoticesFiles/"
    "Final%20FAQs%20on%20QR%20code%2021.07.2023.pdf"
)
FDA_COUNTERFEIT = "https://www.fda.gov/drugs/buying-using-medicine-safely/counterfeit-medicine"


@dataclass(frozen=True)
class ChecklistItem:
    id: str
    check: str
    why: str
    source: str  # who says so
    source_url: str | None


CHECKLIST: tuple[ChecklistItem, ...] = (
    ChecklistItem(
        "qr_code",
        "Scan the QR code or bar code on the strip or box with a phone, and check that the "
        "brand, batch number, manufacturing date and expiry date shown match the pack.",
        "Since 1 August 2023 the top 300 medicine brands in India (Schedule H2) must carry a "
        "QR/bar code holding these details so that anyone can check the pack is genuine.",
        "CDSCO: Guidance for Identification and Verification of Spurious Drugs; FAQs on "
        "G.S.R. 823(E)",
        CDSCO_GUIDANCE,
    ),
    ChecklistItem(
        "batch_dates",
        "Check that the batch number and the manufacturing and expiry dates are printed "
        "clearly, are the same on the strip and the outer box, and that the medicine has not "
        "expired.",
        "Batch number and dates are what regulators use in recall and quality alerts. They are "
        "also part of the QR-code details.",
        "CDSCO: FAQs on G.S.R. 823(E) (QR code contents)",
        CDSCO_QR_FAQ,
    ),
    ChecklistItem(
        "looks_different",
        "Compare the pack and the tablets with what you normally receive: colour, printing, "
        "logo, spelling, seal and the shape or colour of the tablets.",
        "A pack or medicine that looks different from usual can be a sign of a counterfeit.",
        "US FDA: Counterfeit Medicine",
        FDA_COUNTERFEIT,
    ),
    ChecklistItem(
        "side_effects",
        "Ask whether the patient noticed a new or unusual side effect, or that the medicine "
        "is not working as usual.",
        "Unexpected effects after a new supply can be a sign of a counterfeit or poor-quality "
        "medicine.",
        "US FDA: Counterfeit Medicine",
        FDA_COUNTERFEIT,
    ),
    ChecklistItem(
        "licensed_source",
        "Buy only from licensed distributors and pharmacies you know, and keep the invoice.",
        "The US FDA advises buying medicines only from licensed pharmacies. An invoice lets the "
        "batch be traced if a problem is found.",
        "US FDA: Counterfeit Medicine (licensed pharmacies); invoices: general good practice",
        FDA_COUNTERFEIT,
    ),
    ChecklistItem(
        "price",
        "Be cautious if the price is much lower than usual for that brand.",
        "An unusually low price can mean the product did not come through the normal supply chain.",
        "General good practice (no official source cited)",
        None,
    ),
    ChecklistItem(
        "report",
        "If something looks wrong, keep the pack aside and consider reporting it to the State "
        "Drugs Controller or CDSCO.",
        "Regulators publish quality alerts from reports and samples like these.",
        "General good practice (no official source cited)",
        None,
    ),
)
