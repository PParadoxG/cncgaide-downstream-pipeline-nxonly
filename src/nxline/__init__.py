"""The NX side: everything that only exists because NX is available.

This package fills both slots: the geometry provider (``partmodel.py`` fills a
``PartModel``, ``kernel.py`` implements ``KernelServices``) and the recognition
provider — NX's own Feature Based Machining recognition, read out by
``journal_native.py`` and published verbatim by ``native.py``.  Because one
package owns both, face identity needs no reconciliation: the PartModel faces
*are* the NX faces.

Ground rules:

* nothing here imports an open-source CAD kernel — NX is the only geometry
  in this process, and the journal enforces it rather than promising it;
* nothing above the seam imports this package;
* ``journal.py`` runs inside NX's own Python (``run_journal.exe``) and is
  never imported by CPython code.

What NX states is what is published: a node's class is NX's ``Type``, its
label is NX's ``TypeDisplayName``, and its attributes are NX's own names and
values — nothing is re-segmented, renamed or re-measured.  The quantities the
pipeline measures for itself live in each node's separate ``derived`` block,
never beside NX's own words.  An unreachable licence is a named degradation,
never a failure: the part keeps whatever it already had and the next sync
retries.
"""
