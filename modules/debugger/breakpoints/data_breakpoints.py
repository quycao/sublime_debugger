from ... typecheck import *
from ... import core
from ... import ui
from ... import dap

class DataBreakpoint:
	def __init__(self, dap: dap.DataBreakpoint, info: dap.DataBreakpointInfoResponse, enabled: bool):
		self.dap = dap
		self.info = info
		self.enabled = True
		self.result = None #type: Optional[dap.BreakpointResult]

	@property
	def verified(self) -> bool:
		if self.result and self.result.verified:
			return True
		return False

	@property
	def image(self) -> ui.Image:
		if not self.enabled:
			return ui.Images.shared.dot_disabled
		if not self.verified:
			return ui.Images.shared.dot_emtpy
		return ui.Images.shared.dot

	@property
	def tag(self) -> Optional[str]:
		return "0x"

	@property
	def name(self) -> str:
		return self.info.description

	def into_json(self) -> dict:
		return {
			'dap': self.dap.into_json(),
			'info': self.info.into_json(),
			'enabled': self.enabled,
		}

	@staticmethod
	def from_json(json: dict) -> 'DataBreakpoint':
		return DataBreakpoint(
			dap.DataBreakpoint.from_json(json['info']),
			dap.DataBreakpointInfoResponse.from_json(json['data']), 
			json['enabled']
		)

class DataBreakpoints:
	def __init__(self):
		self.breakpoints = [] #type: List[DataBreakpoint]
		self.on_updated = core.Event() #type: core.Event[List[DataBreakpoint]]
		self.on_send = core.Event() #type: core.Event[List[DataBreakpoint]]

	def __iter__(self):
		return iter(self.breakpoints)

	def updated(self, send: bool=True):
		self.on_updated(self.breakpoints)
		if send:
			self.on_send(self.breakpoints)
	
	def clear_session_data(self):
		self.breakpoints = list(filter(lambda b: b.info.canPersist, self.breakpoints))
		self.updated(send=False)

	def set_result(self, breakpoint: DataBreakpoint, result: dap.BreakpointResult):
		breakpoint.result = result
		self.updated(send=False)

	def toggle(self, breakpoint: DataBreakpoint):
		breakpoint.enabled = not breakpoint.enabled
		self.updated()

	def edit(self, breakpoint: DataBreakpoint):
		def set_condition(value: str):
			breakpoint.dap.condition = value or None
			self.updated()

		def set_hit_condition(value: str):
			breakpoint.dap.hitCondition = value or None
			self.updated()

		def toggle_enabled():
			self.toggle(breakpoint)

		def remove():
			self.breakpoints.remove(breakpoint)
			self.updated()

		return ui.InputList([
			ui.InputListItemCheckedText(
				set_condition,
				"Condition",
				"Breaks when expression is true",
				breakpoint.dap.condition,
			),
			ui.InputListItemCheckedText(
				set_hit_condition,
				"Count",
				"Breaks when hit count condition is met",
				breakpoint.dap.hitCondition,
			),
			ui.InputListItemChecked (
				toggle_enabled,
				"Enabled", 
				"Disabled",
				breakpoint.enabled,
			),
			ui.InputListItem(
				remove,
				"Remove"
			),
		], placeholder='Edit Breakpoint @ {}'.format(breakpoint.name))

	def add(self, info: dap.DataBreakpointInfoResponse, type: Optional[str]):
		assert info.id, "this info request has no id"
		self.breakpoints.append(
			DataBreakpoint(
				dap=dap.DataBreakpoint(info.id, type, None, None), 
				info=info, 
				enabled=True
			)
		)
		self.updated()

	def remove_unpersistable(self):
		self.breakpoints = list(filter(lambda b: b.info.canPersist, self.breakpoints))
		self.updated()

	def remove_all(self):
		self.breakpoints = []
		self.updated()
