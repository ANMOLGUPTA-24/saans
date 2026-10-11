// Shalimar Bagh Model School - Bad Air Day Protocol
//
// This file IS the protocol. It is not a prompt, and no language model
// writes it or edits it at runtime. Saans may only hold an activity
// outdoors if Cedar returns ALLOW for that activity, that class, and that
// hour's evidence. A principal can read this file, argue with a clause,
// and change a number without touching a line of application code.
//
// Thresholds follow CPCB's national PM2.5 breakpoints (µg/m³, 24h):
//   Good 0-30 | Satisfactory 31-60 | Moderate 61-90
//   Poor 91-120 | Very Poor 121-250 | Severe 250+
// 60 is also India's NAAQS 24-hour standard for PM2.5.

// The school day runs as normal. Everything below is an exception to this.
@id("P0")
@clause("The school day runs outdoors as normal unless a clause below applies.")
permit (principal, action, resource);

// Exertion multiplies dose. A child at games moves roughly three times the
// air through their lungs, so 'Moderate' air at rest is 'Poor' air at play.
@id("P1")
@clause("No vigorous outdoor activity once forecast PM2.5 passes 90 (CPCB Moderate ceiling), because exertion roughly triples the inhaled dose.")
forbid (
  principal,
  action == Saans::Action::"hold_vigorous_outdoors",
  resource
) when { context.peak_pm25 > 90 };

@id("P2")
@clause("No outdoor activity at all once forecast PM2.5 passes 120 (CPCB Very Poor).")
forbid (
  principal,
  action in [Saans::Action::"hold_outdoors", Saans::Action::"hold_vigorous_outdoors"],
  resource
) when { context.peak_pm25 > 120 };

// Children with a diagnosed respiratory condition are protected at the
// legal standard, not at the point the air becomes visibly bad.
@id("P3")
@clause("A class carrying children on the respiratory register stays indoors once forecast PM2.5 passes 60, India's NAAQS 24-hour standard.")
forbid (
  principal,
  action in [Saans::Action::"hold_outdoors", Saans::Action::"hold_vigorous_outdoors"],
  resource
) when { resource.has_register && context.peak_pm25 > 60 };

// A collapsed mixing layer means the city's emissions stay at head height.
// Air this trapped gets worse through the morning, so the forecast peak is
// a floor, not a ceiling.
@id("P4")
@clause("No outdoor activity when the mixing layer is below 500 m and PM2.5 is already above 60: trapped air gets worse through the session.")
forbid (
  principal,
  action in [Saans::Action::"hold_outdoors", Saans::Action::"hold_vigorous_outdoors"],
  resource
) when {
  context.mixing_height_m < 500 && context.peak_pm25 > 60
};

// The dose clauses. These bite on days that look survivable one activity
// at a time and are not survivable in aggregate - the failure mode a daily
// AQI reading cannot see.
//
// Note on what these do NOT say. WHO's weekly guideline works out to about
// 150 µg·h of outdoor exposure per child per week. Delhi spends that before
// Tuesday, so a clause written as "stay under the WHO budget" grounds every
// class every day and tells a principal nothing. The WHO figure is kept as
// the yardstick Saans reports impact against. What it enforces instead is
// avoidable dose: the part of today's exposure the school can still choose
// not to take.

@id("P5")
@clause("An activity does not stay outdoors when moving it would avoid more than 50 ug.h of inhaled dose - a third of a child's WHO weekly budget, recoverable today.")
forbid (
  principal,
  action in [Saans::Action::"hold_outdoors", Saans::Action::"hold_vigorous_outdoors"],
  resource
) when { context.avoidable_dose > 50 };

@id("P6")
@clause("Once a class has taken 100 ug.h today - two thirds of a WHO week in one day - the rest of its outdoor periods come inside.")
forbid (
  principal,
  action in [Saans::Action::"hold_outdoors", Saans::Action::"hold_vigorous_outdoors"],
  resource
) when { context.dose_today >= 100 };

// Containment and protection.
@id("P7")
@clause("Classroom windows shut once forecast PM2.5 passes 60 (NAAQS). The indoor fallback only reduces dose if the windows are actually shut, so this clause is what makes moving a class indoors mean anything.")
forbid (
  principal,
  action == Saans::Action::"keep_windows_open",
  resource
) when { context.peak_pm25 > 60 };

@id("P8")
@clause("Masks are issued to the respiratory register once PM2.5 passes 90, and to every child once it passes 120.")
forbid (
  principal,
  action == Saans::Action::"omit_masks",
  resource
) when {
  (resource.has_register && context.peak_pm25 > 90) || context.peak_pm25 > 120
};
