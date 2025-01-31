from ... typecheck import *
from ... import core
from ... import ui
from ... import dap

import sublime
import os

# note: Breakpoint lines are 1 based (sublime lines are 0 based)
class SourceBreakpoint:
	next_id = 0

	def __init__(self, file: str, line: int, column: Optional[int], enabled: bool) -> None:
		SourceBreakpoint.next_id += 1
		self.id = SourceBreakpoint.next_id
		self.region_name = 'bp{}'.format(self.id)
		self.views = [] #type: List[SourceBreakpointView]

		self.dap = dap.SourceBreakpoint(line, column, None, None, None)
		self._file = file
		self.enabled = enabled
		self.result = None #type: Optional[dap.BreakpointResult]

	@property
	def tag(self) -> str:
		if self.column:
			return '{}:{}'.format(self.line, self.column)
		return str(self.line)

	@property
	def name(self) -> str:
		base, name = os.path.split(self._file)
		return name

	@property
	def file(self): 
		return self._file

	@property
	def line(self) -> int:
		if self.result and self.result.line:
			return self.result.line
		return self.dap.line

	@property
	def column(self) -> Optional[int]:
		if self.result and self.result.column:
			return self.result.column
		return self.dap.column

	@property
	def verified(self):
		if self.result:
			return self.result.verified
		return True

	def into_json(self) -> dict:
		return {
			'file': self.file,
			'line': self.dap.line,
			'column': self.dap.column,
			'enabled': self.enabled,
			'condition': self.dap.condition,
			'logMessage': self.dap.logMessage,
			'hitCondition': self.dap.hitCondition
		}

	@staticmethod
	def from_json(json: dict) -> 'SourceBreakpoint':
		file = json['file']
		line = json['line']
		column = json.get('column')
		enabled = json['enabled']
		breakpoint = SourceBreakpoint(file, line, column, enabled)
		breakpoint.dap.hitCondition = json['condition']
		breakpoint.dap.logMessage = json['logMessage']
		breakpoint.dap.hitCondition = json['hitCondition']
		return breakpoint

	@property
	def image(self) -> ui.Image:
		if not self.enabled:
			return ui.Images.shared.dot_disabled
		if not self.verified:
			return ui.Images.shared.dot_emtpy
		if self.dap.logMessage:
			return ui.Images.shared.dot_log
		if self.dap.condition or self.dap.hitCondition:
			return ui.Images.shared.dot_expr
		return ui.Images.shared.dot

	def scope(self) -> str:
		if not self.enabled:
			return 'markup.ignored.debug'
		if not self.verified:
			return 'markup.ignored.debug'
		return 'text'

	def update_views(self) -> None:
		for view in self.views:
			view.render()

	def add_to_view(self, view: sublime.View) -> None:
		for old_view in self.views:
			if old_view.view.id == view.id:
				old_view.render()
				return

		self.views.append(SourceBreakpointView(self, view))

	def clear_views(self) -> None:
		for view in self.views:
			view.dispose()
		self.views = []

	def __lt__(self, other: 'SourceBreakpoint'):
		return (self.file, self.line, self.column or 0) < (other.file, other.line, other.column or 0)


class SourceBreakpointView:
	def __init__(self, breakpoint: SourceBreakpoint, view: sublime.View):
		self.breakpoint = breakpoint
		self.view = view
		self.column_phantom = None #type: Optional[ui.Phantom]
		self.render()

	def render (self) -> None:
		self.dispose()

		image = self.breakpoint.image
		line = self.breakpoint.line
		column = self.breakpoint.column

		p = self.view.text_point(line - 1, 0)
		
		self.view.add_regions(self.breakpoint.region_name, [sublime.Region(p, p)], scope=self.breakpoint.scope(), icon=image.file, flags=sublime.HIDDEN)

		if column:
			p = self.view.text_point(line - 1, column - 1)
			self.column_phantom = ui.Phantom(ui.Img(image), self.view, sublime.Region(p, p))

	def dispose(self) -> None:
		self.view.erase_regions(self.breakpoint.region_name)
		if self.column_phantom:
			self.column_phantom.dispose()
			self.column_phantom = None

class SourceBreakpoints:
	def __init__(self) -> None:
		self.breakpoints = [] #type: List[SourceBreakpoint]
		self.on_updated = core.Event() #type: core.Event[SourceBreakpoint]
		self.on_send = core.Event() #type: core.Event[SourceBreakpoint]

		self.disposeables = [
			ui.view_activated.add(self.on_view_activated),
			ui.view_modified.add(self.view_modified)
		] #type: List[Any]

		self.sync_dirty_scheduled = False
		self.dirty_views = {} #type: Dict[int, sublime.View]

	def __iter__(self):
		return iter(self.breakpoints)

	def into_json(self) -> list:
		return list(map(lambda b: b.into_json(), self.breakpoints))

	def load_json(self, json: list):
		self.breakpoints = list(map(lambda j: SourceBreakpoint.from_json(j), json))
		self.breakpoints.sort()
		self.add_breakpoints_to_current_view()

	def clear_session_data(self):
		for breakpoint in self.breakpoints:
			if breakpoint.result:
				breakpoint.result = None
				self.updated(breakpoint, send=False)

	def updated(self, breakpoint: SourceBreakpoint, send: bool=True):
		breakpoint.update_views()
		self.on_updated(breakpoint)
		if send:
			self.on_send(breakpoint)

	def dispose(self) -> None:
		for d in self.disposeables:
			d.dispose()
		for bp in self.breakpoints:
			bp.clear_views()

	def edit(self, breakpoint: SourceBreakpoint):
		def set_log(value: str):
			breakpoint.dap.logMessage = value or None
			self.updated(breakpoint)

		def set_condition(value: str):
			breakpoint.dap.condition = value or None
			self.updated(breakpoint)

		def set_hit_condition(value: str):
			breakpoint.dap.hitCondition = value or None
			self.updated(breakpoint)

		def toggle_enabled():
			self.toggle(breakpoint)

		def remove():
			self.remove(breakpoint)

		return ui.InputList([
			ui.InputListItemCheckedText(
				set_log,
				"Log",
				"Message to log, expressions within {} are interpolated",
				breakpoint.dap.logMessage,
			),
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
		], placeholder="Edit Breakpoint in {} @ {}".format(breakpoint.name, breakpoint.tag))

	def remove(self, breakpoint: SourceBreakpoint) -> None:
		breakpoint.clear_views()
		self.breakpoints.remove(breakpoint)
		self.updated(breakpoint)

	def toggle(self, breakpoint: SourceBreakpoint) -> None:
		breakpoint.enabled = not breakpoint.enabled
		self.updated(breakpoint) 

	def breakpoints_for_file(self, file: str) -> List[SourceBreakpoint]:
		r = list(filter(lambda b: b.file == file, self.breakpoints))
		return r

	def get_breakpoint(self, file: str, line: int, column: Optional[int] = None) -> Optional[SourceBreakpoint]:
		for b in self.breakpoints:
			if b.file == file and b.line == line and b.column == column:
				return b
		return None
	
	def get_breakpoints_on_line(self, file: str, line: int) -> List[SourceBreakpoint]:
		r = list(filter(lambda b: b.file == file and b.line == line, self.breakpoints))
		return r

	def add_breakpoint(self, file: str, line: int, column: Optional[int] = None):
		breakpoint = SourceBreakpoint(file, line, column, True)
		self.breakpoints.append(breakpoint)
		self.breakpoints.sort()
		self.updated(breakpoint)
		self.add_breakpoints_to_current_view()
		return breakpoint

	def add_breakpoints_to_current_view(self):
		view = sublime.active_window().active_view()
		if view:
			self.sync_from_breakpoints(view)

	def set_result(self, breakpoint: SourceBreakpoint, result: dap.BreakpointResult) -> None:
		breakpoint.result = result
		self.updated(breakpoint, send=False)	

	def view_modified(self, view: sublime.View):
		if view.file_name() is None:
			return

		if not self.sync_dirty_scheduled:
			ui.Timer(self.sync_dirty, 1, False)
			self.sync_dirty_scheduled = True

		self.dirty_views[view.id()] = view

	def on_view_activated(self, view: sublime.View):
		self.sync_from_breakpoints(view)

	def sync_dirty(self) -> None:
		self.sync_dirty_scheduled = False
		for view in self.dirty_views.values():
			self.sync(view)

	# changes the data model to match up with the view regions
	# adds any breakpoints found in the data model that are not found on the view
	def sync(self, view: sublime.View) -> None:
		file = view.file_name()
		if not file:
			return

		dirty = False
		for b in self.breakpoints:
			if b.file != file:
				continue
			identifier = b.region_name
			regions = view.get_regions(identifier)
			if len(regions) == 0:
				print('Error: Failed to find breakpoint that should be set, re-adding')
				b.add_to_view(view)
				dirty = True
			else:
				dirty = True
				line = view.rowcol(regions[0].a)[0] + 1
				if line != b.line:
					dirty = True
					b.dap.line = line
					self.updated(b, send=False)			

	# moves the view regions to match up with the data model
	def sync_from_breakpoints(self, view: sublime.View) -> None:
		file = view.file_name()
		for breakpoint in self.breakpoints:
			if breakpoint.file != file:
				continue
			breakpoint.add_to_view(view)

