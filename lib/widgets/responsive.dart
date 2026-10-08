import 'package:flutter/material.dart';

/// A single breakpoint is enough here: below it, mobile-style single-pane
/// navigation (Android phones, narrow web windows); at or above it, a
/// master-detail split (web/desktop/tablet).
const double kWideBreakpoint = 900;

bool isWide(BuildContext context) => MediaQuery.sizeOf(context).width >= kWideBreakpoint;

/// Caps how wide a reading column gets on very large screens — a full-width
/// paragraph on an ultrawide monitor is hard to read.
double readingMaxWidth(BuildContext context) {
  final width = MediaQuery.sizeOf(context).width;
  return width > 1400 ? 900 : double.infinity;
}
