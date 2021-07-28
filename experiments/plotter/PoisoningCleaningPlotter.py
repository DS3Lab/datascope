from .Plotter import Plotter
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.base import clone
from queue import Queue

from functools import partial
import ray


class PoisoningCleaningPlotter(Plotter):

    def __init__(self, app, *argv):
        self.name = 'LabelPlotter'
        self.app = app
        self.argv = argv
        self.colormap = {'TMC-Shapley': 'blue', 'G-Shapley': 'orange', 'Leave-One-Out': 'olive', 'KNN-LOO': 'violet', 'KNN-Shapley': 'purple'}
        self.colors = Queue()
        self.colors.put('green')
        self.colors.put('deeppink')
        self.colors.put('skyblue')
        self.colors.put('navy')
        self.colors.put('darkturquoise')
        self.ray = False

    def getColor(self, name):
        if self.colormap.__contains__(name):
            return self.colormap[name]
        else:
            self.colormap[name] = self.colors.get()
            return self.colormap[name]

    def _calculate_res(self, name, s_values, data_num, X_test, metric=None, model_family='custom', **kwargs):
        res_v = s_values
        res_i = np.argsort(-res_v)[::-1]
        cnt = 0
        f = []
        total = 0
        cnt = 0
        
        #initial accuracy
        num_classes = np.max(self.app.y) + 1
        model = self.return_model(model_family, **kwargs)
        y = self.app.y.copy() #make a copy
        X = self.app.X.copy()

        model.fit(X, y)
        if metric is None:
            acc = model.score(X_test, self.app.y_test)
        else:
            y_pred = model.predict(X_test)
            acc = metric(self.app.y_test, y_pred)
        model = clone(model) #reset model
        initial_acc = acc
        iterations = data_num

        if self.ray:
            X_train = self.app.X.copy()
            y_train = self.app.y.copy()
            X_test = self.app.X_test.copy()
            y_test = self.app.y_test.copy()
            watermarked = self.app.flip.copy()

            @ray.remote
            def call_partial_run_one_prediction(iteration):
                if 10*(iteration+1)/iterations % 1 == 0:
                    print('{} out of {} evaluation iterations for {}.'.format(iteration + 1, iterations, name))

                def run_one_prediction(model, X_train, y_train, X_test, y_test, watermarked, iteration, res_i, metric=None):
                    if watermarked[int(res_i[iteration])] == 1:
                        y_train = y_train.copy() #make a copy

                        for i in range(iteration):
                            if watermarked[int(res_i[i])] == 1:
                                # correct the label class
                                y_train[int(res_i[i])] = (y_train[int(res_i[i])] + 1) % num_classes
                        
                        model = clone(model) #reset model
                        model.fit(X_train, y_train)
                        if metric is None:
                            acc = model.score(X_test, y_test)
                        else:
                            y_pred = model.predict(X_test)
                            acc = metric(y_test, y_pred)

                        return acc
                    else:
                        return -1 # nothing changed, save computation and copy the previous result

                partial_run_one_prediction = partial(run_one_prediction, model=model, X_train=X_train, y_train=y_train, 
                                                    X_test=X_test, y_test=y_test, watermarked=watermarked, res_i=res_i, metric=None)

                return partial_run_one_prediction(iteration=iteration)

            futures = [call_partial_run_one_prediction.remote(iteration=iteration) for iteration in range(iterations)]
            f = np.array(ray.get(futures))

            # do some optimizations
            if f[0] == -1:
                f[0] = initial_acc
            for i in range(1, len(f)):
                if f[i] == -1:
                    f[i] = f[i-1] # replace with previous value

        else:

            for i in range(data_num):
                if 10*(i+1)/data_num % 1 == 0:
                    print('{} out of {} evaluation iterations for {}.'.format(i + 1, data_num, name))

                if self.app.watermarked[int(res_i[i])] == 1:
                    # correct the label class
                    y[int(res_i[i])] = (y[int(res_i[i])] + 1) % num_classes 
                    #remove the watermark
                    #X[int(res_i[i]),-1] = X[int(res_i[i]),-3] = \
                    #   X[int(res_i[i]),-30] = X[int(res_i[i]),-57] = 0
                    model.fit(X, y)
                    if metric is None:
                        acc = model.score(X_test, self.app.y_test)
                    else:
                        y_pred = model.predict(X_test)
                        acc = metric(self.app.y_test, y_pred)
                    model = clone(model) #reset model

                f.append(acc)

        x = np.array(range(1, data_num + 1)) / data_num * 100
        x = np.append(x[0:-1:100], x[-1])
        f = np.append(f[0:-1:100], f[-1])

        return x, f

    def plot(self, metric=None, model_family='custom', save_path=None, ray=False, **kwargs):

        self.ray = ray

        data_num = self.app.X.shape[0]

        X_test = self.app.X_test.copy()

        for (name, result) in self.argv:
            x, f = self._calculate_res(name, result, data_num, X_test, metric=metric, model_family=model_family, **kwargs)
            plt.plot(x, np.array(f) * 100, 'o-', color = self.getColor(name), label = name)

        rand_values = np.random.rand(data_num)
        x, f = self._calculate_res("Random", rand_values, data_num, X_test, metric=metric, model_family=model_family, **kwargs)
        plt.plot(x, np.array(f) * 100, '--', color='red', label = "Random", zorder=7)

        plt.xlabel('Fraction of data corrected (%)', fontsize=15)
        plt.ylabel('Robustness accuracy (%)', fontsize=15)
        plt.legend(loc='lower right', prop={'size': 15})
        plt.tight_layout()
        if save_path is not None:
            plt.savefig(save_path, dpi=300)
        plt.show()
        plt.clf()
