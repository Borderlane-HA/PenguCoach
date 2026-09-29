# Health Development and VO2 max fallback

Alpha.45 adds a training-development layer to the Health page. The goal is to answer three practical questions without inventing a single opaque fitness score:

1. Is fitness moving in a useful direction?
2. Is training load changing?
3. Is recovery keeping up?

The UI therefore combines provider VO2 values, pace/power efficiency at comparable average heart rate, training volume, sport mix, training load, HRV and resting heart rate. Missing values stay missing.

## VO2 source priority

PenguCoach keeps provider values and PenguCoach estimates separate.

1. Imported provider VO2/Cardio Fitness values win for that sport.
2. A PenguCoach fallback is exposed only when no imported value is available in the selected context.
3. Fallback values use `source=pengucoach_estimate` and `measurement_kind=estimated` and are never written back as provider measurements.
4. The UI uses a dashed line plus an explicit estimate/data-basis label.

If SparkyFitness exposes Apple Health Cardio Fitness as a custom measurement now or in the future, PenguCoach recognizes labels such as `VO2`, `Cardio Fitness` and `Aerobic Capacity` and stores valid values as SparkyFitness provider data.

## Running estimate

Running estimates are deliberately conservative. A session must have a usable average heart rate, a running speed in the ACSM running range, sufficient duration and a relatively flat summary. Clearly hilly sessions are rejected because total ascent divided by total distance is **not** the same thing as the continuous treadmill grade required by the ACSM equation.

For accepted flat sessions PenguCoach estimates exercise oxygen cost with the ACSM running equation (speed in m/min):

`VO2 exercise = 0.2 * speed + 3.5`

Then it calculates heart-rate reserve:

`HRR fraction = (HR exercise - HR rest) / (HR max - HR rest)`

Research supports treating %HRR as an approximation of **%VO2 reserve**, rather than raw %VO2max. PenguCoach therefore extrapolates as:

`VO2max estimate = 3.5 + (VO2 exercise - 3.5) / HRR fraction`

Low-intensity sessions and sessions whose average HR is too close to max HR are rejected. Recent accepted estimates are median-smoothed rather than exposing a single workout as the headline value.

## Cycling estimate

Cycling speed by itself is never used to estimate VO2 max. Outdoor speed is too dependent on wind, gradient, rolling resistance, drafting and equipment.

Cycling fallback requires:

- measured average power,
- body mass,
- average HR,
- usable resting/max HR context.

The ACSM leg-cycle workload equation is used for oxygen cost:

`VO2 exercise = 7.0 + 10.8 * watts / body_mass_kg`

The same HRR-to-VO2-reserve extrapolation is then applied. Indoor/trainer data receives a stronger data-basis rating than outdoor ride averages because the ACSM relationship was developed for cycle ergometry. Outdoor estimates are intentionally capped below the highest confidence label.

## Data-basis labels

The displayed confidence is a **data-basis indicator**, not a clinical accuracy claim. It considers whether Garmin HR-zone max/resting HR values are available, whether sufficient resting-HR history exists, FIT data quality, workout duration and modality-specific inputs.

Even a value with a good data basis remains an estimate. A laboratory cardiopulmonary exercise test/spiroergometry is the appropriate method when a directly measured VO2 max is required.

## Efficiency trend

Running efficiency uses pace from sufficiently long, not-clearly-hilly runs whose average HR is within a narrow band around the user's median comparable HR. Cycling efficiency uses measured average power at a comparable average HR. PenguCoach does not mathematically “correct” unrelated workouts to a chosen heart rate.

## References

- SparkyFitness feature discussion: https://github.com/CodeWithCJ/SparkyFitness/issues/2248
- Apple Cardio Fitness: https://support.apple.com/en-gb/108790
- Swain et al., relationship between %HR reserve and %VO2 reserve: https://pubmed.ncbi.nlm.nih.gov/9502363/
- Swain & Leutholtz, HR reserve is equivalent to %VO2 reserve, not %VO2max: https://pubmed.ncbi.nlm.nih.gov/9139182/
- ACSM running-equation example/reference: https://pmc.ncbi.nlm.nih.gov/articles/PMC12419060/
- ACSM cycling workload-equation example/reference: https://pmc.ncbi.nlm.nih.gov/articles/PMC12640988/
