import clean_data
import numpy as np
import pandas as pd
from sklearn import linear_model
import random
import Reg_Oracle_Class
import sys

# run from command line: python Reg_Oracle_Fict.py 26 18 True communities reg_oracle 10000 .05 'gamma'
# B, num_sens, printflag, dataset, oracle, max_iters, beta, fairness_def = 100, 18, True, 'communities', 'reg_oracle', 1000, .001, 'gamma'

# get command line arguments
B, num_sens, printflag, dataset, oracle, max_iters, beta, fairness_def = sys.argv[1:]
num_sens = int(num_sens)
printflag = sys.argv[3].lower() == 'true'
B = float(B)
dataset = str(dataset)
oracle = str(oracle)
max_iters = int(max_iters)
beta = float(beta)
fairness_def = str(fairness_def)
random.seed(1)

# print out the invoked parameters
print(
    'Invoked Parameters: C = {}, number of sensitive attributes = {}, random seed = 1, dataset = {}, learning oracle = {}, beta = {}, formulation: {}'.format(
        B,
        num_sens,
        dataset,
        oracle, beta, fairness_def))

# Data Cleaning and Import
f_name = 'clean_{}'.format(dataset)
clean_the_dataset = getattr(clean_data, f_name)
X, X_prime, y = clean_the_dataset(num_sens)

# -----------------------------------------------------------------------------------------------------------

# Heuristic Frank-Wolfe Algorithm for Finding Optimally (FP)-Fair Classifiers

# Inputs:
# data set: (x,x',y), y in [0,1]
# x' are protected features
# A: Oracle for agnostic learning Y via (x,x')
# F: group set (some concept class over x')
# Aud: Oracle for learning A via F | Y = 0
# C parameter controlling the norm of dual variables
# alpha: unfairness tolerance parameter.

# Algorithm
# Initialize p_0 to be the distribution minimizing empirical error A(X,y)
# At time t, given classifiers selected in rounds 1...t-1, sample one uniformly and classify (x,x') | y = 0
# Run Aud on A | (x,x',0) -> this produces a group j*. Check FP(j)-FP. If < 0 set C = -C
# if FP(j)-FP < alpha, stop, output {p_t-1}.
# Re-weight examples as follows:
# y = 0, x' in j*, A = 1 -> w = 1 + C(1/n_{0j}-1/n_0)
# y = 0 x' not in j* -> w = 1-C/n_0
# all other points: w = 1
# let p_t <- A(Y, X, w)
# -----------------------------------------------------------------------------------------------------------
# Helper Functions
# given a sequence of classifiers p, returns decisions on Data set X

# Inputs:
# A: the previous set of decisions (probabilities) up to time iter - 1
# q: the most recent classifier found
# x: the dataset
# y: the labels
# iter: the iteration
#
# Outputs:
# error: the error of the average classifier found thus far
#


def gen_a(q, x, y, A, iter):
    new_preds = np.multiply(1.0 / iter, q.predict(x))
    ds = np.multiply((iter - 1.0) / iter, A)
    ds = np.add(ds, new_preds)
    error = np.mean([np.abs(ds[k] - y[k]) for k in range(len(y))])
    return [error, ds]


# given an algorithms decisions empirical history of decisions A, sensitive variables X_sense, and true y values y_g
# returns the best classifier learning A via X_sense on the set y_g = 0
# K: number of draws from p where we take the subgroup with largest
# discrimination
def get_group(A, p, X, X_sens, y_g, FP, beta, eta):

    A_0 = [a for u, a in enumerate(A) if y_g[u] == 0]
    X_0 = pd.DataFrame([X_sens.iloc[u, :]
                        for u, s in enumerate(y_g) if s == 0])
    m = len(A_0)
    n = float(len(y_g))
    d = X_sens.shape[1]
    func = Reg_Oracle_Class.RandomLinearThresh(d)
    group_members_0 = func.predict(X_0)
    err_group = np.mean([np.abs(group_members_0[i] - A_0[i])
                         for i in range(len(A_0))])
    # get the false positive rate in group
    if sum(group_members_0) == 0:
        fp_group_rate = 0
    else:
        fp_group_rate = np.mean(
            [r for t, r in enumerate(A_0) if group_members_0[t] == 1])
    fp_disp_rate = fp_group_rate - FP
    return [func, np.abs(fp_disp_rate), fp_group_rate, err_group, np.sign(fp_disp_rate)]


# p is a classifier
# X is the data
# X_sens is the sensitive data
# y_g are the values
# g is the group
# calculates the false positive rate disparity of p with respect to a
# specific group g
def calc_disp(p, X, y_g, X_sens, g):
    A_p = p.predict(X)
    FP = [A_p[i] for i, c in enumerate(y_g) if c == 0]
    FP = np.mean(FP)
    group_members = g.predict(X_sens)
    fp_g = [A_p[i]
            for i, c in enumerate(y_g) if group_members[i] == 1 and c == 0]
    if len(fp_g) == 0:
        return 0
    fp_g = np.mean(fp_g)
    return np.abs(FP - fp_g)


# given a sequence of classifiers we want to print out the unfairness in
# each marginal coordinate
def calc_unfairness(A, X_prime, y_g, FP_p):
    unfairness = []
    n = X_prime.shape[1]
    sens_means = np.mean(X_prime, 0)
    for q in range(n):
        group_members = [X_prime.iloc[i, q] > sens_means[q]
                         for i in range(X_prime.shape[0])]
        # calculate FP rate on group members
        fp_g = [a for t, a in enumerate(
            A) if group_members[t] == 1 and y_g[t] == 0]
        if len(fp_g) > 0:
            fp_g = np.mean(fp_g)
        else:
            fp_g = 0
        # calculate the fp rate on non-group members
        group_members_neg = [1 - g for g in group_members]
        # calculate FP rate on group members
        fp_g_neg = [a for t, a in enumerate(
            A) if group_members_neg[t] == 1 and y_g[t] == 0]
        if len(fp_g_neg) > 0:
            fp_g_neg = np.mean(fp_g_neg)
        else:
            fp_g_neg = 0
        unfairness.append(
            np.max([np.abs(np.mean(fp_g) - FP_p), np.abs(np.mean(fp_g_neg) - FP_p)]))
    return unfairness


# update c1 for y = 0
def learner_costs(c_1, f, X_prime, y, B, iteration, fp_disp, group_size_0, beta):
    # store whether FP disparity was + or -
    pos_neg = f[4]
    X_0_prime = pd.DataFrame([X_prime.iloc[u, :] for u,s in enumerate(y) if s == 0])
    g_members = f[0].predict(X_0_prime)
    m = len(c_1)
    n = float(len(y))
    g_weight_0 = np.sum(g_members)*(1.0/float(m))
    for t in range(m):
        new_group_cost = (1.0/n)*pos_neg*B*(1.0/iteration) * g_members[t] * (g_weight_0 - 1)
        if fairness_def == 'alpha_beta':
            if np.abs(fp_disp) < beta:
                if t == 0:
                    print('barrier')
                new_group_cost = 0
        if fairness_def == 'gamma':
            if np.abs(fp_disp)*group_size_0 < beta:
                if t == 0:
                    print('barrier')
                new_group_cost = 0
        c_1[t] = (c_1[t] - 1.0/n) * ((iteration-1.0)/iteration) + new_group_cost + 1.0/n
    return c_1


def learner_br(c_1t, X, y, eta):
    c_1t_new = c_1t[:]
    c_0 = [eta] * n
    c_1 = []
    for r in range(n):
        if y[r] == 1:
            c_1.append((-1.0/n) + eta)
        else:
            c_1.append(c_1t_new.pop(0) + eta)
    reg0 = linear_model.LinearRegression()
    reg0.fit(X, c_0)
    reg1 = linear_model.LinearRegression()
    reg1.fit(X, c_1)
    func = Reg_Oracle_Class.RegOracle(reg0, reg1)
    return func


def fit_weighted(q, x, y_t):
    cost_0 = [0 if tuna == 0 else q[r] for r, tuna in enumerate(y_t)]
    cost_1 = [0 if tuna == 1 else q[r] for r, tuna in enumerate(y_t)]
    reg0 = linear_model.LinearRegression()
    reg0.fit(x, cost_0)
    reg1 = linear_model.LinearRegression()
    reg1.fit(x, cost_1)
    primal_model = Reg_Oracle_Class.RegOracle(reg0, reg1)
    return primal_model


def lagrangian_value(groups, yhat, B, FP, X, X_prime, y, iteration):
    lagrange = 0
    n = len(y)
    err_pt = np.mean([np.abs(yhat[r]-y[r]) for r in range(n)])
    for g in groups:
        g_mems = g.predict(X_prime)
        fp_g = np.mean([yhat[i] for i in range(n) if y[i] == 0 and g_mems[i] == 1])
        fp_disp = fp_g-FP
        group_size_0 = np.sum(f[0].predict(X_0)) * (1.0/n)
        lagrange += B*1.0/(iteration-1.0)*fp_disp*group_size_0
    return lagrange + err_pt







# -----------------------------------------------------------------------------------------------------------
# Fictitious Play Algorithm

# add to costs to stabilize performance
eta = 1
stop = False
n = X.shape[0]
m = len([s for s in y if s == 0])
p = [learner_br([1.0/n]*m, X, y, eta)]
iteration = 1
errors_t = []
fp_diff_t = []
coef_t = []
size_t = []
groups = []
cum_group_mems = []
m = len([s for s in y if s == 0])
c_1t = [1.0 / n] * m
FP = 0
A = [0.0] * n
group_membership = [0.0] * n
X_0 = pd.DataFrame([X_prime.iloc[u, :] for u, s in enumerate(y) if s == 0])


while iteration < max_iters:
    print('iteration: {}'.format(iteration))
    eta = 1.0/iteration
    # get t-1 mixture decisions on X by randomizing on current set of p
    emp_p = gen_a(p[-1], X, y, A, iteration)
    # get the error of the t-1 mixture classifier
    err = emp_p[0]
    # Average decisions
    A = emp_p[1]
    # update FP to get the false positive rate of the mixture classifier
    A_recent = p[-1].predict(X)
    # FP rate of t-1 mixture on new group g_t
    FP_recent = np.mean([A_recent[i] for i, c in enumerate(y) if c == 0])
    FP = ((iteration - 1.0) / iteration) * FP + FP_recent * (1.0 / iteration)
    # dual player best responds to strategy up to t-1
    f = get_group(A, p, X, X_prime, y, FP, beta, eta)
    # flag whether FP disparity was positive or negative
    pos_neg = f[4]
    fp_disparity = f[1]
    # compute list of people who have been included in an identified subgroup up to time t
    group_membership = np.add(group_membership, f[0].predict(X_prime))
    group_membership = [g != 0 for g in group_membership]
    group_size_0 = np.sum(f[0].predict(X_0))*(1.0/n)
    # cumulative group members up to time t
    group_members_t = np.sum(group_membership)
    cum_group_mems.append(group_members_t)

    # primal player best responds: cost-sensitive classification
    p_t = learner_br(c_1t, X, y, eta)
    A_t = p_t.predict(X)
    FP_t = np.mean([A_t[i] for i, c in enumerate(y) if c == 0])
    # get lagrangian value which primal player is minimizing
    #lagrange = lagrangian_value(groups, A_t, B, FP_t, X, X_prime, y, iteration)
    lagrange = 0


    # calculate the FP rate of the new p_t on the last group found
    fp_rate_after_fit = 0
    if iteration > 1:
        fp_rate_after_fit = calc_disp(
            p_t, X, y, X_prime, groups[len(groups) - 1])
    # append new group, new p, fp_diff of group found, coefficients, group size
    groups.append(f[0])
    p.append(p_t)
    fp_diff_t.append(np.abs(f[1]))
    errors_t.append(err)
    #coef_t.append(f[0].b0.coef_ - f[0].b1.coef_)
    group_size = np.mean(f[0].predict(X_0))
    size_t.append(group_size)
    if iteration == 1:
        print(
            'most accurate classifier accuracy: {}, most acc-class unfairness: {}, most acc-class size {}'.format(
                err,
                fp_diff_t[0],
                size_t[0]))
    # get unfairness on marginal subgroups
    unfairness = calc_unfairness(A, X_prime, y, FP)
    # print
    if printflag:
        print('XX iteration: {}, average error, FP group diff, Group_Size_0, Lagrangian of p_t, Cum_group, group_size_0*FP_diff: {} {} {} {} {} {}'.format(iteration, '{:f}'.format(err), '{:f}'.format(np.abs(f[1])), '{:f}'.format(group_size_0), '{:f}'.format(lagrange), '{:f}'.format(cum_group_mems[-1]), '{:f}'.format(group_size_0*np.abs(f[1]))))
        group_coef = f[0].coefficient
        print('YY coefficients of g_t: {}'.format(group_coef),)
        learner_coef = p_t.b0.coef_-p_t.b1.coef_
        print('ZZ coefficients of learner t: {}'.format(learner_coef),)
        # print('Unfairness in marginal subgroups: {}'.format(unfairness),)

    # update costs: the primal player best responds
    c_1t = learner_costs(c_1t, f, X_prime, y, B, iteration, fp_disparity, group_size_0, beta)
    print('UU learner costs: {}'.format(np.unique(c_1t)))
    sys.stdout.flush()
    iteration += 1
    iteration = float(iteration)

