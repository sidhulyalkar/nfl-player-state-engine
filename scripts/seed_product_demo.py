from __future__ import annotations

from player_state_engine.product.demo import seed_product_demo


if __name__ == "__main__":
    for name, path in seed_product_demo().items():
        print(f"{name}: {path}")
