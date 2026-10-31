"""Parametric technical drawings generated from the component models.

SVG for viewing, DXF (via ezdxf) for CAD import. Every drawing is regenerated
from the design data, so a design change updates the drawings. Drawings are
2D layout drawings at the preliminary design level: contours, sections and
key dimensions, with a title block. They are not manufacturing drawings.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np

from .assembly import EngineBuild

INK = "#1a1a1a"
DIM = "#1f5fa8"
HATCH = "#9a9a9a"
FLUID = {"LOX": "#1f6fd1", "LCH4": "#c2410c", "CH4 (supercritical)": "#d97706", "ox-rich gas": "#0e7490",
         "fuel-rich gas": "#b45309"}


class Svg:
    """Minimal SVG writer working in millimetres, y up (flipped on output)."""

    def __init__(self, width: float, height: float, margin: float = 10.0):
        self.w, self.h, self.m = width, height, margin
        self.items: list[str] = []

    def _y(self, y: float) -> float:
        return self.h - y

    def line(self, x1, y1, x2, y2, color=INK, width=0.35, dash: str | None = None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<line x1="{x1:.2f}" y1="{self._y(y1):.2f}" x2="{x2:.2f}" y2="{self._y(y2):.2f}" '
                          f'stroke="{color}" stroke-width="{width}"{d}/>')

    def polyline(self, xs, ys, color=INK, width=0.4, fill="none", close=False, dash=None):
        pts = " ".join(f"{x:.2f},{self._y(y):.2f}" for x, y in zip(xs, ys))
        tag = "polygon" if close else "polyline"
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<{tag} points="{pts}" fill="{fill}" stroke="{color}" stroke-width="{width}"{d}/>')

    def rect(self, x, y, w, h, color=INK, width=0.35, fill="none"):
        self.items.append(f'<rect x="{x:.2f}" y="{self._y(y + h):.2f}" width="{w:.2f}" height="{h:.2f}" '
                          f'fill="{fill}" stroke="{color}" stroke-width="{width}"/>')

    def circle(self, x, y, r, color=INK, width=0.3, fill="none"):
        self.items.append(f'<circle cx="{x:.2f}" cy="{self._y(y):.2f}" r="{r:.3f}" fill="{fill}" stroke="{color}" '
                          f'stroke-width="{width}"/>')

    def text(self, x, y, s, size=3.0, color=INK, anchor="start", weight="normal", rotate=0.0):
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        rot = f' transform="rotate({rotate:.1f} {x:.2f} {self._y(y):.2f})"' if rotate else ""
        self.items.append(f'<text x="{x:.2f}" y="{self._y(y):.2f}" font-size="{size}" fill="{color}" '
                          f'text-anchor="{anchor}" font-weight="{weight}" font-family="Helvetica, Arial, sans-serif"{rot}>{s}</text>')

    def arrow(self, x1, y1, x2, y2, color=DIM, width=0.25):
        self.line(x1, y1, x2, y2, color, width)
        a = math.atan2(y2 - y1, x2 - x1)
        for side in (+1, -1):
            self.line(x2, y2, x2 - 2.0 * math.cos(a + side * 0.35), y2 - 2.0 * math.sin(a + side * 0.35), color, width)

    def dim_h(self, x1, x2, y, label, ext_from: tuple[float, float] | None = None):
        """Horizontal dimension at height y between x1 and x2."""
        if ext_from:
            self.line(x1, ext_from[0], x1, y - 1, DIM, 0.18)
            self.line(x2, ext_from[1], x2, y - 1, DIM, 0.18)
        self.arrow((x1 + x2) / 2, y, x1, y)
        self.arrow((x1 + x2) / 2, y, x2, y)
        self.text((x1 + x2) / 2, y + 1.2, label, 2.6, DIM, "middle")

    def dim_v(self, x, y1, y2, label, ext_from: tuple[float, float] | None = None):
        if ext_from:
            self.line(ext_from[0], y1, x + 1, y1, DIM, 0.18)
            self.line(ext_from[1], y2, x + 1, y2, DIM, 0.18)
        self.arrow(x, (y1 + y2) / 2, x, y1)
        self.arrow(x, (y1 + y2) / 2, x, y2)
        self.text(x - 1.2, (y1 + y2) / 2, label, 2.6, DIM, "middle", rotate=-90)

    def title_block(self, number: str, title: str, material: str, scale: str, notes: list[str]):
        bw, bh = 150.0, 34.0
        x0, y0 = self.w - self.m - bw, self.m
        self.rect(x0, y0, bw, bh, INK, 0.5)
        self.line(x0, y0 + 22, x0 + bw, y0 + 22, INK, 0.3)
        self.line(x0, y0 + 11, x0 + bw, y0 + 11, INK, 0.3)
        self.line(x0 + 100, y0, x0 + 100, y0 + 22, INK, 0.3)
        self.text(x0 + 3, y0 + 26, title, 4.2, INK, weight="bold")
        self.text(x0 + 3, y0 + 14.5, f"Material: {material}", 2.8)
        self.text(x0 + 3, y0 + 3.5, "Raptor-class engine study, raptor_sim. PRELIMINARY: not for manufacture", 2.3)
        self.text(x0 + 103, y0 + 14.5, f"DWG {number}", 3.2, weight="bold")
        self.text(x0 + 103, y0 + 3.5, f"Scale {scale}   {date.today().isoformat()}", 2.4)
        for k, n in enumerate(notes):
            self.text(self.m, self.m + 3 + 4.0 * (len(notes) - 1 - k), n, 2.6)

    def save(self, path: Path):
        frame = (f'<rect x="{self.m / 2:.1f}" y="{self.m / 2:.1f}" width="{self.w - self.m:.1f}" '
                 f'height="{self.h - self.m:.1f}" fill="none" stroke="{INK}" stroke-width="0.6"/>')
        body = "\n".join(self.items)
        path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}mm" height="{self.h}mm" '
            f'viewBox="0 0 {self.w} {self.h}">\n<rect width="100%" height="100%" fill="white"/>\n{frame}\n{body}\n</svg>\n'
        )


def _dxf():
    import ezdxf

    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    for name, color in (("CONTOUR", 7), ("LINER", 1), ("CLOSEOUT", 5), ("CENTER", 3), ("ANNOTATION", 2)):
        doc.layers.add(name, color=color)
    doc.layers.get("CENTER").dxf.linetype = "CENTER"
    return doc


# --------------------------------------------------------------------------------------
def thrust_chamber(b: EngineBuild, out: Path) -> list[Path]:
    """DWG RC-100: thrust chamber assembly half section."""
    c = b.contour
    st = b.cooling.stations
    x = np.array([s.x for s in st]) * 1e3
    r_in = np.array([s.r for s in st]) * 1e3
    r_liner = r_in + np.array([s.wall_thickness + s.depth for s in st]) * 1e3
    r_chan_in = r_in + np.array([s.wall_thickness for s in st]) * 1e3
    r_out = r_liner + np.array([s.closeout_thickness for s in st]) * 1e3
    scale = 0.12
    x0, y0 = 50.0, 165.0  # drawing position of the injector face on the axis
    X = lambda v: x0 + (v - x[0]) * scale  # noqa: E731
    Y = lambda v: y0 + v * scale  # noqa: E731
    length = x[-1] - x[0]
    svg = Svg(max(X(x[-1]) + 60, 420.0), 297.0)
    # axis
    svg.line(X(x[0]) - 8, y0, X(x[-1]) + 8, y0, DIM, 0.25, "6,2,1,2")
    # half section: liner (hatched band) and closeout
    svg.polyline(np.r_[X(x), X(x[::-1])], np.r_[Y(r_in), Y(r_liner[::-1])], INK, 0.35, "#f0d9c4", close=True)
    svg.polyline(np.r_[X(x), X(x[::-1])], np.r_[Y(r_liner), Y(r_out[::-1])], INK, 0.35, "#d6dbe3", close=True)
    svg.polyline(X(x), Y(r_chan_in), "#b45309", 0.2, dash="1.5,1")
    # mirror (outline only, lower half)
    svg.polyline(X(x), Y(-r_in), INK, 0.3)
    svg.polyline(X(x), Y(-r_out), INK, 0.3)
    svg.line(X(x[0]), Y(-r_out[0]), X(x[0]), Y(r_out[0]), INK, 0.5)
    svg.line(X(x[-1]), Y(-r_out[-1]), X(x[-1]), Y(-r_in[-1]), INK, 0.3)
    # material break: GRCop to IN718
    for s0, s1 in zip(st[:-1], st[1:]):
        if s0.material != s1.material:
            xb = X(s1.x * 1e3)
            svg.line(xb, Y(s1.r * 1e3) - 2, xb, Y((s1.r + s1.wall_thickness + s1.depth + s1.closeout_thickness) * 1e3) + 4,
                     "#7c2d12", 0.3, "2,1")
            svg.text(xb + 1, Y(s1.r * 1e3 + 30) + 4, f"GRCop-42 | IN718 at area ratio {s1.area_ratio:.1f}", 2.4, "#7c2d12")
    # dimensions
    xt = X(0.0)
    svg.dim_h(X(x[0]), xt, Y(-r_out.max()) - 12, f"{-x[0]:.0f}", (Y(-r_out[0]), Y(-c.rt * 1e3)))
    svg.dim_h(xt, X(x[-1]), Y(-r_out.max()) - 12, f"{x[-1]:.0f}", (Y(-c.rt * 1e3), Y(-r_out[-1])))
    svg.dim_h(X(x[0]), X(x[-1]), Y(-r_out.max()) - 22, f"{length:.0f} overall", (Y(-r_out[0]) - 13, Y(-r_out[-1]) - 13))
    svg.dim_v(xt + 3, Y(-c.rt * 1e3), Y(c.rt * 1e3), f"ø{2 * c.rt * 1e3:.1f} throat")
    svg.dim_v(X(x[0]) - 6, Y(-c.rc * 1e3), Y(c.rc * 1e3), f"ø{2 * c.rc * 1e3:.1f} chamber")
    svg.dim_v(X(x[-1]) + 10, Y(-c.re * 1e3), Y(c.re * 1e3), f"ø{2 * c.re * 1e3:.0f} exit")
    thn, the = c.bell_angles_deg
    svg.text(X(x[-1] * 0.25), Y(r_out.max() * 0.62), f"Rao 80% bell: θn {thn:.1f}°, θe {the:.1f}°", 2.8, DIM)
    svg.text(X(x[0]) + 2, Y(c.rc * 1e3) + 8, "INJECTOR FACE", 2.6, DIM)
    svg.text(X(x[0]) + 2, y0 + 2, "℄", 3, DIM)
    cool = b.inputs.cooling
    notes = [
        "NOTES",
        f"1. Inner contour: L* {c.inputs.l_star:.2f} m, contraction ratio {c.inputs.contraction_ratio:.1f}, "
        f"convergent {c.inputs.convergent_half_angle_deg:.0f}°, throat arcs 1.5 Rt / 0.382 Rt.",
        f"2. Coolant channels: {st[[s.x for s in st].index(min((s.x for s in st), key=abs))].n_channels} at throat, "
        f"hot wall {cool.hot_wall_thickness * 1e3:.2f} mm (throat), {cool.copper_nozzle_wall_thickness * 1e3:.2f} mm "
        f"(copper nozzle), {cool.nozzle_wall_thickness * 1e3:.2f} mm (IN718 nozzle).",
        f"3. Closeout IN718, thickness {min(s.closeout_thickness for s in st) * 1e3:.1f}-{max(s.closeout_thickness for s in st) * 1e3:.1f} mm. "
        "Coolant enters at the exit manifold and flows toward the injector.",
        "4. Dimensions in mm. Contour table in RC-100_contour.csv.",
    ]
    svg.title_block("RC-100", "Thrust chamber assembly, half section", "GRCop-42 liner, IN718 nozzle and closeout",
                    f"1:{1 / scale:.1f}", notes)
    p_svg = out / "RC-100_thrust_chamber.svg"
    svg.save(p_svg)

    # contour table
    p_csv = out / "RC-100_contour.csv"
    with p_csv.open("w") as f:
        f.write("x_mm,r_inner_mm,r_channel_bottom_mm,r_liner_outer_mm,r_closeout_outer_mm,area_ratio,material,"
                "n_channels,channel_width_mm,channel_depth_mm,rib_mm\n")
        for s, a_, b_, c_, d_ in zip(st, r_in, r_chan_in, r_liner, r_out):
            f.write(f"{s.x * 1e3:.3f},{a_:.3f},{b_:.3f},{c_:.3f},{d_:.3f},{s.area_ratio:.4f},{s.material},"
                    f"{s.n_channels},{s.width * 1e3:.3f},{s.depth * 1e3:.3f},{s.rib * 1e3:.3f}\n")

    # DXF, full scale mm, revolve profile about the X axis in CAD
    doc = _dxf()
    msp = doc.modelspace()
    msp.add_lwpolyline(list(zip(x, r_in)), dxfattribs={"layer": "CONTOUR"})
    msp.add_lwpolyline(list(zip(x, r_liner)), dxfattribs={"layer": "LINER"})
    msp.add_lwpolyline(list(zip(x, r_out)), dxfattribs={"layer": "CLOSEOUT"})
    msp.add_line((x[0] - 50, 0), (x[-1] + 50, 0), dxfattribs={"layer": "CENTER"})
    msp.add_line((x[0], r_in[0]), (x[0], r_out[0]), dxfattribs={"layer": "CONTOUR"})
    msp.add_line((x[-1], r_in[-1]), (x[-1], r_out[-1]), dxfattribs={"layer": "CONTOUR"})
    msp.add_text("RC-100 THRUST CHAMBER PROFILE - REVOLVE ABOUT X", dxfattribs={"layer": "ANNOTATION", "height": 12}
                 ).set_placement((x[0], -150))
    p_dxf = out / "RC-100_thrust_chamber.dxf"
    doc.saveas(p_dxf)
    return [p_svg, p_dxf, p_csv]


def channel_section(b: EngineBuild, out: Path) -> list[Path]:
    """DWG RC-110-A: coolant channel cross-section at the throat and in the nozzle."""
    st = b.cooling.stations
    throat = min(st, key=lambda s: abs(s.x))
    nozzle = max((s for s in st if s.material == "GRCop-42"), key=lambda s: s.x)
    svg = Svg(297.0, 210.0)
    sizes = [(3 * (s.width + s.rib) + s.rib, s.wall_thickness + s.depth + s.closeout_thickness) for s in (throat, nozzle)]
    scale = math.floor(min(12.0, min(95.0 / (w * 1e3) for w, _ in sizes), min(70.0 / (h * 1e3) for _, h in sizes)))
    for k, (s, label) in enumerate(((throat, "SECTION A-A at throat"), (nozzle, f"SECTION B-B at area ratio {nozzle.area_ratio:.1f}"))):
        ox, oy = 25.0 + k * 135.0, 95.0
        w, d, t, rib, tc = (v * 1e3 for v in (s.width, s.depth, s.wall_thickness, s.rib, s.closeout_thickness))
        pitch = w + rib
        n_show = 3
        total = n_show * pitch + rib
        # liner block with channels cut out (unrolled, flat approximation)
        svg.rect(ox, oy, total * scale, (t + d) * scale, INK, 0.4, "#f0d9c4")
        svg.rect(ox, oy + (t + d) * scale, total * scale, tc * scale, INK, 0.4, "#d6dbe3")
        for i in range(n_show):
            cx = ox + (rib + i * pitch) * scale
            svg.rect(cx, oy + t * scale, w * scale, d * scale, INK, 0.4, "white")
        svg.text(ox, oy - 6, "HOT GAS SIDE", 2.6, "#b91c1c")
        svg.text(ox, oy + (t + d + tc) * scale + 4, label, 3.2, INK, weight="bold")
        x1 = ox + rib * scale
        svg.dim_h(x1, x1 + w * scale, oy + (t + d) * scale + tc * scale + 12, f"{w:.2f}")
        svg.dim_h(x1 + w * scale, x1 + pitch * scale, oy - 12, f"rib {rib:.2f}")
        svg.dim_v(ox + total * scale + 6, oy + t * scale, oy + (t + d) * scale, f"{d:.2f}")
        svg.dim_v(ox + total * scale + 14, oy, oy + t * scale, f"{t:.2f}")
        svg.dim_v(ox + total * scale + 22, oy + (t + d) * scale, oy + (t + d + tc) * scale, f"{tc:.1f}")
        svg.text(ox, oy - 18, f"{s.n_channels} channels, {s.material}; q = {s.q / 1e6:.0f} MW/m², "
                 f"hot wall {s.t_wall_gas:.0f} K, coolant {s.t_coolant:.0f} K, {s.p_coolant / 1e5:.0f} bar", 2.5)
    svg.title_block("RC-110-A", "Coolant channel sections", "GRCop-42 liner, IN718 closeout", f"{scale:.0f}:1",
                    ["NOTES", "1. Unrolled section (curvature not shown). Dimensions in mm.",
                     "2. Channel geometry varies along the chamber; see RC-100_contour.csv."])
    p = out / "RC-110-A_channel_sections.svg"
    svg.save(p)
    doc = _dxf()
    msp = doc.modelspace()
    w, d, t, rib = (v * 1e3 for v in (throat.width, throat.depth, throat.wall_thickness, throat.rib))
    for i in range(3):
        cx = rib + i * (w + rib)
        msp.add_lwpolyline([(cx, t), (cx + w, t), (cx + w, t + d), (cx, t + d)], close=True, dxfattribs={"layer": "LINER"})
    msp.add_lwpolyline([(0, 0), (3 * (w + rib) + rib, 0), (3 * (w + rib) + rib, t + d), (0, t + d)], close=True,
                       dxfattribs={"layer": "CONTOUR"})
    p2 = out / "RC-110-A_throat_channel.dxf"
    doc.saveas(p2)
    return [p, p2]


def injector_face(b: EngineBuild, out: Path) -> list[Path]:
    """DWG IN-200: main injector face pattern."""
    inj = b.injector
    rc = b.contour.rc * 1e3
    svg = Svg(297.0, 297.0)
    scale = 0.50
    cx, cy = 115.0, 160.0
    svg.circle(cx, cy, rc * scale, INK, 0.6)
    svg.circle(cx, cy, inj.usable_face_radius * 1e3 * scale + inj.annulus_outer_diameter * 1e3 / 2 * scale, DIM, 0.2)
    for x, y in inj.positions():
        X, Y = cx + x * 1e3 * scale, cy + y * 1e3 * scale
        svg.circle(X, Y, inj.annulus_outer_diameter * 1e3 / 2 * scale, "#b45309", 0.15)
        svg.circle(X, Y, inj.post_inner_diameter * 1e3 / 2 * scale, "#0e7490", 0.15, "#0e7490")
    svg.dim_h(cx - rc * scale, cx + rc * scale, cy - rc * scale - 10, f"ø{2 * rc:.1f} chamber")
    # detail of one element
    dx, dy, ds = 262.0, 230.0, 3.0
    svg.circle(dx, dy, inj.annulus_outer_diameter * 1e3 / 2 * ds, "#b45309", 0.4, "#fde7d2")
    svg.circle(dx, dy, inj.post_outer_diameter * 1e3 / 2 * ds, INK, 0.4, "#dddddd")
    svg.circle(dx, dy, inj.post_inner_diameter * 1e3 / 2 * ds, "#0e7490", 0.4, "#cdeef3")
    svg.text(dx, dy + 24, "DETAIL C (3:1)", 3.0, INK, "middle", "bold")
    rows = [
        f"Ox post ID ø{inj.post_inner_diameter * 1e3:.2f}, OD ø{inj.post_outer_diameter * 1e3:.2f}",
        f"Fuel annulus OD ø{inj.annulus_outer_diameter * 1e3:.2f} (gap {(inj.annulus_outer_diameter - inj.post_outer_diameter) * 500:.2f})",
        f"Element pitch {inj.element_pitch * 1e3:.2f}, post recess {b.inputs.injector.post_recess * 1e3:.1f}",
        f"Ox-rich gas {inj.ox_temperature:.0f} K, {inj.ox_velocity:.0f} m/s",
        f"Fuel-rich gas {inj.fuel_temperature:.0f} K, {inj.fuel_velocity:.0f} m/s",
    ]
    for k, r_ in enumerate(rows):
        svg.text(dx - 30, dy - 18 - 4.5 * k, r_, 2.3)
    svg.title_block("IN-200", "Main injector face pattern", "IN718 face, ox-compatible superalloy posts", f"1:{1 / scale:.1f}",
                    ["NOTES", f"1. {inj.placed_elements} gas-gas shear coaxial elements on {len(inj.rings)} rings.",
                     f"2. Injector drop {inj.pressure_drop / 1e5:.0f} bar ({inj.pressure_drop / b.perf.design.pc:.0%} of Pc).",
                     f"3. Face plate {inj.face_thickness * 1e3:.1f} mm. Dimensions in mm."])
    p = out / "IN-200_injector_face.svg"
    svg.save(p)
    doc = _dxf()
    msp = doc.modelspace()
    msp.add_circle((0, 0), rc, dxfattribs={"layer": "CONTOUR"})
    for x, y in inj.positions():
        msp.add_circle((x * 1e3, y * 1e3), inj.annulus_outer_diameter * 1e3 / 2, dxfattribs={"layer": "LINER"})
        msp.add_circle((x * 1e3, y * 1e3), inj.post_outer_diameter * 1e3 / 2, dxfattribs={"layer": "CONTOUR"})
        msp.add_circle((x * 1e3, y * 1e3), inj.post_inner_diameter * 1e3 / 2, dxfattribs={"layer": "CLOSEOUT"})
    p2 = out / "IN-200_injector_face.dxf"
    doc.saveas(p2)
    return [p, p2]


def turbopump(b: EngineBuild, out: Path, which: str) -> list[Path]:
    """DWG TP-300 / TP-400: turbopump layout (meridional half section, schematic)."""
    tp = b.fuel_tp if which == "fuel" else b.ox_tp
    pn = "TP-300" if which == "fuel" else "TP-400"
    p, t = tp.pump, tp.turbine
    svg = Svg(297.0, 210.0)
    s = 280.0 / max(1.2, (0.45 * p.stages + 0.9) * p.impeller_diameter + 0.35) * 0.55  # mm per m... pick scale
    s = min(s, 250.0)
    ox, oy = 30.0, 80.0
    k = s  # drawing mm per metre
    x = ox
    # inducer
    rid = p.inducer_diameter / 2
    svg.polyline([x, x + 0.6 * rid * 2 * k, x + 0.6 * rid * 2 * k, x], [oy + 0.3 * rid * k, oy + 0.3 * rid * k, oy + rid * k, oy + rid * k],
                 INK, 0.4, "#e5e7eb", close=True)
    svg.text(x, oy + rid * k + 3, "inducer", 2.4)
    x += 0.6 * rid * 2 * k + 4
    r2 = p.impeller_diameter / 2
    for i in range(p.stages):
        w = 0.12 * p.impeller_diameter * k
        svg.polyline([x, x + w, x + w, x + w * 0.6, x], [oy + 0.25 * r2 * k, oy + 0.25 * r2 * k, oy + r2 * k, oy + r2 * k, oy + 0.45 * r2 * k],
                     INK, 0.4, "#e5e7eb", close=True)
        svg.text(x, oy + r2 * k + 3, f"stage {i + 1}", 2.4)
        x += w + 0.25 * p.impeller_diameter * k
    if tp.kick_stage_diameter > 0:
        rk = tp.kick_stage_diameter / 2
        w = 0.15 * tp.kick_stage_diameter * k
        svg.rect(x, oy + 0.3 * rk * k, w, 0.7 * rk * k, INK, 0.4, "#fde68a")
        svg.text(x, oy + rk * k + 3, "kick stage", 2.4)
        x += w + 10
    x += 15
    # turbine disc + blades
    rm = t.mean_diameter / 2
    h = t.blade_height
    svg.rect(x, oy, 0.05 * k + 2, (rm - h / 2) * k, INK, 0.4, "#d1d5db")
    svg.rect(x, oy + (rm - h / 2) * k, 0.05 * k + 2, h * k, INK, 0.4, "#fca5a5")
    svg.text(x, oy + (rm + h / 2) * k + 3, "turbine", 2.4)
    x_end = x + 0.05 * k + 12
    # shaft and axis
    svg.rect(ox - 5, oy, x_end - ox + 5, tp.shaft_diameter / 2 * k, INK, 0.3, "#9ca3af")
    svg.line(ox - 10, oy, x_end + 10, oy, DIM, 0.25, "6,2,1,2")
    svg.dim_v(ox + 0.6 * rid * 2 * k + 2, oy, oy + r2 * k, f"R{r2 * 1e3:.0f}")
    svg.dim_v(x - 3, oy, oy + rm * k, f"Rm {rm * 1e3:.0f}")
    svg.dim_h(ox - 5, x_end, oy - 12, f"{(x_end - ox + 5) / k * 1e3:.0f} rotor length (approx.)")
    data = [
        f"Speed {p.rpm:,.0f} rpm, power {tp.power / 1e6:.1f} MW, torque {tp.torque / 1e3:.1f} kN m, shaft ø{tp.shaft_diameter * 1e3:.0f}",
        f"Pump: {p.flow:.0f} kg/s, head {p.head:,.0f} m, {p.stages} stage(s), tip speed {p.tip_speed:.0f} m/s, "
        f"η {p.efficiency_predicted:.3f} predicted",
        f"Inducer ø{p.inducer_diameter * 1e3:.0f}, NPSH {p.npsh_available:.0f} m, S = {p.suction_specific_speed_us:,.0f} (US)",
        f"Turbine: {t.flow:.0f} kg/s, inlet {t.inlet_temperature:.0f} K / {t.inlet_pressure / 1e5:.0f} bar, PR {t.pressure_ratio:.2f}, "
        f"u/c0 {t.velocity_ratio:.2f}, η {t.efficiency_predicted:.3f}",
        f"Blade height {t.blade_height * 1e3:.1f} mm, tip speed {t.tip_speed:.0f} m/s, root stress {t.blade_root_stress / 1e6:.0f} MPa",
        f"Estimated mass {tp.mass:.0f} kg (±50%)",
    ]
    for i, d in enumerate(data):
        svg.text(20, 190 - 5 * i, d, 2.7)
    svg.title_block(pn, f"{tp.name.capitalize()} layout (schematic)", f"Impeller {p.material}, turbine {t.material}",
                    f"1:{1000 / k:.1f}", ["NOTES", "1. Meridional half section, schematic proportions.",
                                         "2. Housings, bearings and seals not drawn."])
    path = out / f"{pn}_{which}_turbopump.svg"
    svg.save(path)
    return [path]


def flow_schematic(b: EngineBuild, out: Path) -> list[Path]:
    """DWG ES-001: engine flow schematic with pressures and temperatures (P&ID style)."""
    svg = Svg(420.0, 297.0)
    fu, ox = b.cycle.fuel_shaft, b.cycle.ox_shaft
    L = {ln.tag: ln for ln in b.lines}
    V = {v.line: v for v in b.valves}

    def box(x, y, w, h, label, sub="", fill="#f3f4f6"):
        svg.rect(x, y, w, h, INK, 0.5, fill)
        svg.text(x + w / 2, y + h / 2 + 1, label, 3.0, INK, "middle", "bold")
        if sub:
            svg.text(x + w / 2, y + h / 2 - 3.5, sub, 2.3, INK, "middle")

    def pipe(pts, tag):
        ln = L[tag]
        xs, ys = zip(*pts)
        svg.polyline(xs, ys, FLUID.get(ln.fluid, INK), 1.1)
        mx, my = pts[len(pts) // 2]
        svg.text(mx + 1.5, my + 1.5, f"{tag} ø{ln.inner_diameter * 1e3:.0f}", 2.2, FLUID.get(ln.fluid, INK))
        if tag in V:
            v = V[tag]
            (x1, y1), (x2, y2) = pts[-2], pts[-1]
            vx, vy = (x1 + x2) / 2, (y1 + y2) / 2
            svg.polyline([vx - 3, vx + 3, vx + 3, vx - 3], [vy - 2, vy + 2, vy - 2, vy + 2], INK, 0.4, "white", close=True)
            svg.text(vx + 4, vy - 4, v.tag, 2.3, INK)

    # components
    box(30, 230, 50, 18, "LOX inlet", f"{b.inputs.cycle.p_pump_inlet / 1e5:.0f} bar, 90 K", "#dbeafe")
    box(300, 230, 50, 18, "CH4 inlet", f"{b.inputs.cycle.p_pump_inlet / 1e5:.0f} bar, 112 K", "#ffedd5")
    box(30, 170, 60, 22, "LOX pump" + (" + kick stage" if b.inputs.cycle.ox_kick_stage else ""), f"{ox.pump_discharge_pressure / 1e5:.0f} bar, {b.ox_tp.pump.rpm:,.0f} rpm")
    box(290, 170, 70, 22, "CH4 pump" + (" + kick stage" if b.inputs.cycle.fuel_kick_stage else ""),
        f"{fu.pump_discharge_pressure / 1e5:.0f} bar, {b.fuel_tp.pump.rpm:,.0f} rpm")
    box(30, 110, 60, 22, "Ox-rich preburner", f"{ox.preburner_pressure / 1e5:.0f} bar, {ox.turbine_inlet_temperature:.0f} K", "#ccfbf1")
    box(290, 110, 70, 22, "Fuel-rich preburner", f"{fu.preburner_pressure / 1e5:.0f} bar, {fu.turbine_inlet_temperature:.0f} K", "#fef3c7")
    box(30, 70, 60, 18, "Ox turbine", f"{b.ox_tp.turbine.efficiency_predicted:.2f} η, PR {ox.turbine_pressure_ratio:.2f}")
    box(290, 70, 70, 18, "Fuel turbine", f"{b.fuel_tp.turbine.efficiency_predicted:.2f} η, PR {fu.turbine_pressure_ratio:.2f}")
    box(160, 60, 80, 22, "Main injector", f"{b.injector.manifold_pressure / 1e5:.0f} bar manifold")
    box(160, 25, 80, 28, "Thrust chamber", f"Pc {b.perf.design.pc / 1e5:.0f} bar, {b.perf.design.thrust_sl / 1e3:,.0f} kN SL")
    box(175, 140, 50, 30, "Cooling jacket", f"{b.cooling.pressure_drop / 1e5:.0f} bar drop, {b.cooling.heat_load / 1e6:.0f} MW", "#fee2e2")
    # shafts
    svg.line(60, 92, 60, 110, INK, 0.3, "2,1")
    svg.line(325, 92, 325, 110, INK, 0.3, "2,1")
    # lines
    pipe([(55, 230), (55, 192)], "L01")
    pipe([(325, 230), (325, 192)], "L02")
    pipe([(50, 170), (50, 132)], "L03")
    pipe([(80, 170), (80, 150), (300, 150), (300, 132)], "L04")
    pipe([(355, 181), (380, 181), (380, 160), (225, 160)], "L05")
    pipe([(200, 140), (200, 125), (290, 125)], "L06")
    pipe([(290, 176), (110, 176), (110, 125), (90, 125)], "L07")
    pipe([(90, 76), (125, 76), (160, 76)], "L08")
    pipe([(290, 76), (265, 76), (240, 76)], "L09")
    svg.line(200, 60, 200, 53, INK, 1.0)
    for k, (name, col) in enumerate(FLUID.items()):
        svg.line(100, 55 - 5 * k, 110, 55 - 5 * k, col, 1.1)
        svg.text(112, 54 - 5 * k, name, 2.4)
    svg.title_block("ES-001", "Engine flow schematic", "-", "NTS",
                    ["NOTES", "1. Full-flow staged combustion. All fuel and all oxygen pass through a preburner.",
                     "2. Pressures and temperatures at the design point from the component iteration.",
                     "3. Valve tags as in the BOM (VA-7xx)."])
    p = out / "ES-001_flow_schematic.svg"
    svg.save(p)
    return [p]


def make_all(b: EngineBuild, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    paths += thrust_chamber(b, out)
    paths += channel_section(b, out)
    paths += injector_face(b, out)
    paths += turbopump(b, out, "fuel")
    paths += turbopump(b, out, "ox")
    paths += flow_schematic(b, out)
    return paths
