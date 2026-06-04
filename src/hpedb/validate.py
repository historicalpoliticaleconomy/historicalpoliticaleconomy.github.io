from typing import TypedDict


class ValidationCase(TypedDict):
    doi:          str
    label:        str
    expected_hpe: bool


# Ground-truth cases used by both `hpedb-classify --validate` and the db pytest suite.
CASES: list[ValidationCase] = [
    # HPE — direct historical study
    {"doi": "10.1257/aer.20200885",     "label": "Merchant Towns — Blaydes & Paik (2022)",           "expected_hpe": True},
    {"doi": "10.1093/qje/qjy011",       "label": "Protestant Reformation — Cantoni et al. (2018)",    "expected_hpe": True},
    {"doi": "10.3982/ecta11484",         "label": "Great Reform Act — Aidt & Franck (2015)",           "expected_hpe": True},
    # HPE — persistence papers
    {"doi": "10.1093/qje/qjt005",       "label": "Women and the Plough — Alesina et al. (2013)",      "expected_hpe": True},
    {"doi": "10.1093/qje/qjy024",       "label": "The Mission — Valencia (2019)",                     "expected_hpe": True},
    {"doi": "10.1093/qje/qjae023",      "label": "Jim Crow — Shertzer et al. (2024)",                 "expected_hpe": True},
    # NOT HPE
    {"doi": "10.1017/s0003055420000180", "label": "Democracy by Mistake — Treisman (2020)",           "expected_hpe": False},
    {"doi": "10.1257/aer.104.9.2872",   "label": "Emissions Pass-through — Fabra & Reguant (2014)",  "expected_hpe": False},
    {"doi": "10.1093/qje/qjaa023",      "label": "Randomizing Religion — Clingingsmith et al. (2020)","expected_hpe": False},
    {"doi": "10.1257/aer.103.1.80",     "label": "School Admissions — Pathak & Sonmez (2013)",       "expected_hpe": False},
    {"doi": "10.1257/aer.103.4.1463",   "label": "Monetary Transmission — Lenel (2013)",             "expected_hpe": False},
]
