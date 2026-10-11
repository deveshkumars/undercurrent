"""LLM-agent population simulations.

Two modes share one agent bank:
- panel: Park et al. (2024) "Generative Agent Simulations of 1,000 People" style message tests;
  each agent (persona transcript + four expert reflections) answers a questionnaire under every arm.
- social: POSIM (2026) style opinion spread; Social-BDI agents act on a simulated feed, activity is
  driven by a Hawkes process, and interventions branch from checkpoints.
"""
