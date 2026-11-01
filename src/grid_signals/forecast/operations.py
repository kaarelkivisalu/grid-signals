"""Product operations shared by the installed CLI and Prefect lifecycle."""

from datetime import date, timedelta

from grid_signals.products import PRODUCTS


def forecast(product_id: str, delivery: date | None = None, *, refresh: bool = True):
    from grid_signals.forecast import publication
    from grid_signals.forecast.pipelines import load, predict, price_forward
    from grid_signals.forecast.sources import load as observed_load
    from grid_signals.forecast.sources import prices

    product = PRODUCTS[product_id]
    if product.adapter == "renewable":
        return predict.run(
            delivery,
            product.zone,
            product.target,
            refresh=refresh,
            resolution=product.resolution,
        )
    delivery = delivery or (publication.now().date() + timedelta(days=1))
    if refresh:
        start, end = delivery - timedelta(days=8), delivery + timedelta(days=1)
        if product.adapter == "load":
            observed_load.fetch(start, end, refresh=True)
        else:
            prices.refresh(start, end)
    return (
        load.publish(delivery)
        if product.adapter == "load"
        else price_forward.publish(delivery)
    )
