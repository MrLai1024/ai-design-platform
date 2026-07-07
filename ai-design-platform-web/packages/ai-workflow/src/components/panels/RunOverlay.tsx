import React, { useState } from 'react';
import { useAppSelector } from '../../store';
import { useWorkflowRun } from '../../composables/useWorkflowRun';

export function RunOverlay() {
  const runLogs = useAppSelector(s => s.workflow.runLogs);
  const { humanConfirm, submitHumanConfirm } = useWorkflowRun();
  const [formValues, setFormValues] = useState<Record<string, unknown>>({});
  const logsEndRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [runLogs]);

  return (
    <>
      {/* Log panel */}
      <div className="absolute bottom-4 left-4 right-80 max-h-48 bg-gray-900 text-green-400 rounded-lg shadow-xl overflow-hidden z-10">
        <div className="px-3 py-2 bg-gray-800 text-xs font-mono text-gray-400 flex items-center justify-between">
          <span>运行日志</span>
          <span className="text-green-500">● 运行中</span>
        </div>
        <div className="p-3 overflow-y-auto max-h-36 font-mono text-xs leading-relaxed">
          {runLogs.map((log, i) => <div key={i}>{log}</div>)}
          <div ref={logsEndRef} />
        </div>
      </div>

      {/* Human confirm dialog */}
      {humanConfirm && (
        <div className="absolute inset-0 bg-black/40 flex items-center justify-center z-20">
          <div className="bg-white rounded-xl shadow-2xl p-6 w-96 max-w-[90vw]">
            <h3 className="text-lg font-semibold text-gray-800 mb-2">✋ 人工确认</h3>
            <p className="text-sm text-gray-600 mb-4">{humanConfirm.message}</p>
            <div className="space-y-3">
              {humanConfirm.fields.map(field => (
                <div key={field.key}>
                  <label className="block text-sm font-medium text-gray-700 mb-1">{field.label}</label>
                  {field.type === 'boolean' ? (
                    <div className="flex gap-4">
                      <label className="flex items-center gap-2">
                        <input type="radio" name={field.key} value="true"
                          onChange={() => setFormValues({ ...formValues, [field.key]: true })}
                          className="text-blue-600" />
                        <span className="text-sm">是</span>
                      </label>
                      <label className="flex items-center gap-2">
                        <input type="radio" name={field.key} value="false"
                          onChange={() => setFormValues({ ...formValues, [field.key]: false })} />
                        <span className="text-sm">否</span>
                      </label>
                    </div>
                  ) : (
                    <input type="text"
                      onChange={e => setFormValues({ ...formValues, [field.key]: e.target.value })}
                      className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500" />
                  )}
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button onClick={() => submitHumanConfirm(formValues)}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg">确认</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
