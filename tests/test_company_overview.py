from corporate_atlas.services.company_overview import annual_financials


def test_annual_financials_aligns_and_deduplicates_fiscal_periods():
    def fact(start, end, filed, val, form='10-K'):
        return dict(start=start, end=end, filed=filed, val=val, form=form)

    previous = ('2023-10-01', '2024-09-28')
    current = ('2024-09-29', '2025-09-27')
    revenue = [
        fact(*previous, '2024-11-01', 100),
        fact(*previous, '2025-11-01', 110),
        fact(*current, '2025-11-01', 130),
        fact('2025-06-29', '2025-09-27', '2025-11-01', 45),
        fact('2025-09-28', '2026-01-03', '2026-02-01', 50, '10-Q'),
    ]
    income = [
        fact(*previous, '2025-11-01', 11),
        fact(*current, '2025-11-01', -13),
        fact('2025-06-29', '2025-09-27', '2025-11-01', 4),
    ]
    payload = {'facts': {'us-gaap': {
        'RevenueFromContractWithCustomerExcludingAssessedTax': {'units': {'USD': revenue}},
        'NetIncomeLoss': {'units': {'USD': income, 'EUR': [fact(*current, '2025-11-01', 100)]}},
    }}}

    periods = annual_financials(payload)
    assert [(row['period_end'], row['revenue'], row['net_income'], row['net_margin']) for row in periods] == [
        ('2024-09-28', 110, 11, 10),
        ('2025-09-27', 130, -13, -10),
    ]
