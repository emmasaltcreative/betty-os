# Project Principles

Engineering constitution for BettyOS.

## Build only what today's sprint requires

Future ideas belong in the Product Vision and Roadmap—not in code or Architecture. Architecture describes the system as it exists today.

## Core principles

- **Build the smallest thing that works.** Ship the minimum that delivers real value; grow only when use demands it.
- **Readability over cleverness.** Code should be easy to follow. Prefer plain structure over clever abstractions.
- **Delay abstractions.** Extract shared patterns only when a second real use appears.
- **If it isn’t needed today, don’t build it.** Unused features and speculative layers add cost without return.
- **Local-first.** Data and workflows live as files on disk. No cloud dependency is required to run BettyOS.
- **Prefer the Python standard library.** Add a third-party package only when it clearly earns its place.
- **Every dependency earns its place.** Each package needs a concrete justification.
- **Every file justifies its existence.** No placeholder architecture or empty scaffolding beyond what the sprint needs.
- **Keep the engine generic; keep brand knowledge in brand profiles.** Core logic stays reusable across brands. Brand-specific content lives under `brands/`.

## What we avoid

Frameworks, plugin systems, interfaces, registries, and module boundaries are not documented or built until a real implementation requires them.
