"""Population and genetic diversity: an individual-based demographic simulation.

Each person carries two alleles at L neutral loci. Every founder and every
immigrant brings brand-new allele identifiers, so two copies of the same
identifier in one person are identical by descent: the share of homozygous loci
is the inbreeding coefficient F measured against the founders. Expected
heterozygosity (1 - sum p^2) tracks how much founder diversity is left.

Demography (annual steps):
  * deaths from a Gompertz hazard fitted to the life-expectancy input (estimate)
  * births to women aged 18-42 at a rate that gives the target fertility, with
    fertility falling to replacement as the population nears habitat capacity K
  * random mating among men aged 18-60 (the best case for diversity; real
    pair-bonding and family size variance lower Ne)
  * optional immigrants each launch window (every synodic period)
  * optional donor-gamete births from a frozen bank shipped from Earth (a share
    of all births; with no men left, all births use the bank)

Verification: wright_fisher_check() runs the same allele machinery in the
textbook Wright-Fisher setting and compares it with H_t = H_0 (1 - 1/2N)^t.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

from .inputs import v

SYNODIC_YEARS = 779.94 / 365.25  # Earth-Mars synodic period; see growth.synodic_period_days
GENERATION_YEARS = 29.0  # mean age of mothers at birth, high-income Earth (estimate)
GOMPERTZ_B = 0.085  # 1/yr, adult mortality doubling ~8 yr (estimate, human demography norm)


def gompertz_a(life_expectancy: float, b: float = GOMPERTZ_B) -> float:
    """Gompertz baseline hazard giving the requested life expectancy at birth."""

    def e0(a: float) -> float:
        ages = np.arange(0, 130, 0.25)
        surv = np.exp(-a / b * (np.exp(b * ages) - 1))
        return float(np.trapezoid(surv, ages))

    return brentq(lambda a: e0(a) - life_expectancy, 1e-7, 1e-1)


@dataclass
class PopulationScenario:
    founders: int = 160
    years: int = 300
    capacity: int = 1000  # habitat capacity K (persons)
    tfr: float = field(default_factory=lambda: v("tfr_target"))
    life_expectancy: float = field(default_factory=lambda: v("life_expectancy"))
    immigrants_per_window: int = 0
    immigration_years: int = 0  # immigration stops after this many years
    bank_share: float = 0.0  # share of births using donor gametes from a frozen bank shipped from Earth
    loci: int = 100
    catastrophe_rate: float = 0.0  # chance per year of a mass-casualty event (estimate)
    catastrophe_kill: float = 0.3  # share of people lost in one event (estimate)
    seed: int = 1


@dataclass
class PopulationResult:
    years: np.ndarray
    population: np.ndarray
    heterozygosity: np.ndarray  # expected heterozygosity, founders ~1.0
    inbreeding: np.ndarray  # observed identical-by-descent homozygosity F
    founder_alleles_kept: np.ndarray  # share of founder allele copies still present
    extinct: bool
    births: int
    deaths: int

    def ne_estimate(self, from_year: int = 50) -> float:
        """Effective size from heterozygosity decay per generation after from_year."""
        i0 = from_year
        h0, h1 = self.heterozygosity[i0], self.heterozygosity[-1]
        gens = (self.years[-1] - self.years[i0]) / GENERATION_YEARS
        if h1 <= 0 or h0 <= 0 or gens <= 0 or h1 >= h0:
            return math.inf
        per_gen = (h1 / h0) ** (1 / gens)
        return 1.0 / (2.0 * (1.0 - per_gen))


def _founder_alleles_kept(alleles: np.ndarray, founder_ids: int, founders: int) -> float:
    if len(alleles) == 0:
        return 0.0
    kept = 0
    for j in range(alleles.shape[1]):
        u = np.unique(alleles[:, j, :])
        kept += int((u < founder_ids).sum())
    return kept / (alleles.shape[1] * 2 * founders)


def _heterozygosity(alleles: np.ndarray) -> tuple[float, float]:
    """Expected heterozygosity and observed IBD homozygosity, averaged over loci."""
    n, loci, _ = alleles.shape
    if n == 0:
        return 0.0, 0.0
    hs = np.empty(loci)
    for j in range(loci):
        _, counts = np.unique(alleles[:, j, :], return_counts=True)
        p = counts / (2 * n)
        hs[j] = 1.0 - np.sum(p * p)
    f_obs = float(np.mean(alleles[:, :, 0] == alleles[:, :, 1]))
    return float(hs.mean()), f_obs


class _Ids:
    def __init__(self) -> None:
        self.next = 0

    def new(self, shape: tuple[int, ...]) -> np.ndarray:
        n = int(np.prod(shape))
        out = np.arange(self.next, self.next + n, dtype=np.int64).reshape(shape)
        self.next += n
        return out


def simulate(s: PopulationScenario) -> PopulationResult:
    rng = np.random.default_rng(s.seed)
    ids = _Ids()
    a = gompertz_a(s.life_expectancy)

    def newcomers(n: int, age_lo: float, age_hi: float):
        age = rng.uniform(age_lo, age_hi, n)
        sex = np.arange(n) % 2  # balanced sexes
        rng.shuffle(sex)
        return age, sex, ids.new((n, s.loci, 2))

    age, sex, alleles = newcomers(s.founders, 20, 40)
    founder_ids = ids.next
    years, pop, het, inb, kept = [], [], [], [], []
    births = deaths = 0
    next_window = 0.0

    for year in range(s.years + 1):
        h, f = _heterozygosity(alleles)
        years.append(year)
        pop.append(len(age))
        het.append(h)
        inb.append(f)
        kept.append(_founder_alleles_kept(alleles, founder_ids, s.founders))
        if year == s.years:
            break

        # Immigration at each launch window
        if s.immigrants_per_window and year < s.immigration_years and year >= next_window:
            ia, isx, ial = newcomers(s.immigrants_per_window, 20, 40)
            age, sex, alleles = np.concatenate([age, ia]), np.concatenate([sex, isx]), np.concatenate([alleles, ial])
        if year >= next_window:
            next_window += SYNODIC_YEARS

        # Births
        n = len(age)
        women = np.flatnonzero((sex == 0) & (age >= 18) & (age < 42))
        men = np.flatnonzero((sex == 1) & (age >= 18) & (age < 60))
        if len(women) and (len(men) or s.bank_share):
            crowd = max(0.0, 1.0 - n / s.capacity)
            tfr_eff = 2.05 + (s.tfr - 2.05) * crowd if s.tfr > 2.05 else s.tfr
            mothers = women[rng.random(len(women)) < tfr_eff / 24.0]
            nb = len(mothers)
            if nb:
                kids = np.empty((nb, s.loci, 2), dtype=np.int64)
                pick_m = rng.integers(0, 2, (nb, s.loci))
                kids[:, :, 0] = np.take_along_axis(alleles[mothers], pick_m[:, :, None], 2)[:, :, 0]
                n_bank = int(rng.binomial(nb, s.bank_share)) if s.bank_share else 0
                n_local = nb - n_bank
                if n_local and len(men):
                    fathers = rng.choice(men, n_local)
                    pick_f = rng.integers(0, 2, (n_local, s.loci))
                    kids[:n_local, :, 1] = np.take_along_axis(alleles[fathers], pick_f[:, :, None], 2)[:, :, 0]
                elif n_local:
                    n_bank, n_local = nb, 0
                if n_bank:
                    kids[n_local:, :, 1] = ids.new((n_bank, s.loci))
                age = np.concatenate([age, np.zeros(nb)])
                sex = np.concatenate([sex, rng.integers(0, 2, nb)])
                alleles = np.concatenate([alleles, kids])
                births += nb

        # Deaths over the coming year (Gompertz plus 0.3% infant mortality)
        hazard = a / GOMPERTZ_B * (np.exp(GOMPERTZ_B * (age + 1)) - np.exp(GOMPERTZ_B * age))
        p_die = 1 - np.exp(-hazard)
        p_die[age < 1] += 0.003
        if s.catastrophe_rate and rng.random() < s.catastrophe_rate:
            p_die = 1 - (1 - p_die) * (1 - s.catastrophe_kill)
        alive = rng.random(len(age)) >= p_die
        deaths += int((~alive).sum())
        age, sex, alleles = age[alive] + 1, sex[alive], alleles[alive]

    pop_arr = np.array(pop)
    # Extinct: nobody left, or no woman left, or no man and no gamete bank.
    extinct = pop_arr[-1] == 0 or not ((sex == 0).any() and ((sex == 1).any() or s.bank_share > 0))
    return PopulationResult(np.array(years), pop_arr, np.array(het), np.array(inb), np.array(kept), bool(extinct), births, deaths)


def wright_fisher_check(n: int = 100, generations: int = 40, loci: int = 200, reps: int = 8, seed: int = 3):
    """Same allele machinery in an ideal Wright-Fisher population.

    Returns (simulated H_t/H_0, analytic (1 - 1/2N)^t). Verification gate: they
    agree within a few percent.
    """
    rng = np.random.default_rng(seed)
    ratios = []
    for _ in range(reps):
        ids = _Ids()
        al = ids.new((n, loci, 2))
        h0, _ = _heterozygosity(al)
        for _ in range(generations):
            par = rng.integers(0, n, (n, 2))  # each gene copy from a random parent (selfing allowed)
            pick = rng.integers(0, 2, (n, loci, 2))
            new = np.empty_like(al)
            for k in range(2):
                new[:, :, k] = np.take_along_axis(al[par[:, k]], pick[:, :, k : k + 1], 2)[:, :, 0]
            al = new
        ht, _ = _heterozygosity(al)
        ratios.append(ht / h0)
    return float(np.mean(ratios)), (1 - 1 / (2 * n)) ** generations


def viability_study(
    founder_sizes=(20, 50, 100, 160, 500, 2000),
    years: int = 300,
    reps: int = 20,
    capacity_factor: float = 3.0,
    **kw,
) -> list[dict]:
    """Closed-colony Monte Carlo: extinction risk and diversity kept, per founder size."""
    out = []
    for n0 in founder_sizes:
        r = max(4, reps if n0 <= 500 else reps // 5)
        ext, het, inb, ne, pops, kept = [], [], [], [], [], []
        for k in range(r):
            res = simulate(PopulationScenario(founders=n0, years=years, capacity=int(capacity_factor * n0), seed=1000 * n0 + k, **kw))
            ext.append(res.extinct)
            het.append(res.heterozygosity[-1] / res.heterozygosity[0])
            inb.append(res.inbreeding[-1])
            kept.append(res.founder_alleles_kept[-1])
            pops.append(res.population[-1])
            if not res.extinct:
                ne.append(res.ne_estimate())
        out.append(
            {
                "founders": n0,
                "runs": r,
                "extinction_probability": float(np.mean(ext)),
                "heterozygosity_kept": float(np.mean(het)),
                "inbreeding_F": float(np.mean(inb)),
                "founder_alleles_kept": float(np.mean(kept)),
                "final_population_mean": float(np.mean(pops)),
                "ne_estimate": float(np.median(ne)) if ne else 0.0,
            }
        )
    return out
