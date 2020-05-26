# Copyright 2016-2020 Tecnativa - Carlos Dauden
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.tools import float_round


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.multi
    def action_confirm(self):
        if not self.env.context.get('bypass_risk', False):
            risk_amount = self.currency_id._convert(
                self.amount_total, self.company_id.currency_id,
                self.company_id, fields.Date.today())
            partner = self.partner_id.commercial_partner_id
            exception_msg = ""
            if partner.risk_exception:
                exception_msg = _("Financial risk exceeded.\n")
            elif partner.risk_sale_order_limit and (
                    (partner.risk_sale_order + risk_amount) >
                    partner.risk_sale_order_limit):
                exception_msg = _(
                    "This sale order exceeds the sales orders risk.\n")
            elif partner.risk_sale_order_include and (
                    (partner.risk_total + risk_amount) >
                    partner.credit_limit):
                exception_msg = _(
                    "This sale order exceeds the financial risk.\n")
            if exception_msg:
                return self.env['partner.risk.exceeded.wiz'].create({
                    'exception_msg': exception_msg,
                    'partner_id': partner.id,
                    'origin_reference': '%s,%s' % ('sale.order', self.id),
                    'continue_method': 'action_confirm',
                }).action_show()
        return super(SaleOrder, self).action_confirm()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    risk_amount = fields.Monetary(
        string="Risk amount",
        compute='_compute_risk_amount',
        compute_sudo=True,
        store=True
    )
    # TODO: Analyze performance vs order_id.partner_id.commercial_partner_id
    commercial_partner_id = fields.Many2one(
        related='order_partner_id.commercial_partner_id',
        string='Commercial Entity',
        store=True,
        index=True,
    )

    @api.depends('state',
                 'price_reduce_taxinc',
                 'qty_delivered',
                 'product_uom_qty',
                 'qty_invoiced')
    def _compute_risk_amount(self):
        for line in self:
            if line.state != 'sale':
                line.risk_amount = 0.0
                continue
            qty = line.product_uom_qty
            if line.product_id.invoice_policy == 'delivery':
                qty = max(qty, line.qty_delivered)
            risk_qty = float_round(
                qty - line.qty_invoiced,
                precision_rounding=line.product_uom.rounding)
            # There is no risk if the line hasn't stock moves to deliver
            # Added hasattr condition because fails in post-migration compute
            if risk_qty and line.qty_delivered_method == 'stock_move' and (
                    hasattr(line, 'move_ids')):
                if not line.move_ids.filtered(
                        lambda move: move.state not in ('done', 'cancel')):
                    risk_qty = line.qty_to_invoice
            if risk_qty == 0.0:
                line.risk_amount = 0.0
                continue
            if line.product_uom_qty:
                # This method has more precision that using price_reduce_taxinc
                risk_amount = line.price_total * (
                    risk_qty / line.product_uom_qty)
            else:
                risk_amount = line.price_reduce_taxinc * risk_qty
            line.risk_amount = line.order_id.currency_id._convert(
                risk_amount, line.company_id.currency_id,
                line.company_id, fields.Date.today())
